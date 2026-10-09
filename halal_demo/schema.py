"""Trade proposal schema. Agents may fill it in. They cannot grade it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from halal_demo.clock import ensure_utc, parse_utc
from halal_demo.decimals import parse_decimal

ASSET_CLASSES = frozenset({"forex", "gold", "stock", "crypto"})
VENUES = frozenset({"mt5", "alpaca_paper", "binance_spot_testnet"})
DIRECTIONS = frozenset({"buy", "sell"})
VENUE_FOR_CLASS = {
    "forex": "mt5",
    "gold": "mt5",
    "stock": "alpaca_paper",
    "crypto": "binance_spot_testnet",
}
REQUIRED = (
    "proposal_id",
    "idempotency_id",
    "instrument",
    "asset_class",
    "venue",
    "contract_type",
    "direction",
    "entry",
    "size",
    "max_estimated_loss",
    "data_source",
    "data_timestamp",
    "strategy",
    "evidence",
    "expiry",
)


@dataclass(frozen=True)
class TradeProposal:
    proposal_id: str
    idempotency_id: str
    instrument: str
    asset_class: str
    venue: str
    contract_type: str
    direction: str
    entry: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    size: Decimal
    max_estimated_loss: Decimal
    data_source: str
    data_timestamp: datetime
    strategy: str
    evidence: str
    expiry: datetime
    claimed_shariah_result: str | None = None
    claimed_risk_result: str | None = None


@dataclass(frozen=True)
class ParseResult:
    proposal: TradeProposal | None
    reasons: tuple[str, ...]
    proposal_id: str | None = None
    idempotency_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.proposal is not None and not self.reasons


def _text(data: dict, field: str, reasons: list[str]) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        reasons.append(f"incomplete:{field}")
        return ""
    return value.strip()


def parse_proposal(data: object, now: datetime) -> ParseResult:
    reasons: list[str] = []
    if not isinstance(data, dict):
        return ParseResult(None, ("malformed:proposal_not_object",), None, None)
    now = ensure_utc(now, "now")
    for field in REQUIRED:
        if field not in data or data[field] in (None, ""):
            reasons.append(f"incomplete:{field}")
    proposal_id = _text(data, "proposal_id", reasons) if "proposal_id" in data else ""
    idempotency_id = _text(data, "idempotency_id", reasons) if "idempotency_id" in data else ""
    if idempotency_id and not _idempotency_ok(idempotency_id):
        reasons.append("malformed:idempotency_id")
    instrument = _text(data, "instrument", reasons) if "instrument" in data else ""
    asset_class = _text(data, "asset_class", reasons) if "asset_class" in data else ""
    venue = _text(data, "venue", reasons) if "venue" in data else ""
    contract_type = _text(data, "contract_type", reasons) if "contract_type" in data else ""
    direction = _text(data, "direction", reasons) if "direction" in data else ""
    strategy = _text(data, "strategy", reasons) if "strategy" in data else ""
    evidence = _text(data, "evidence", reasons) if "evidence" in data else ""
    data_source = _text(data, "data_source", reasons) if "data_source" in data else ""
    if asset_class and asset_class not in ASSET_CLASSES:
        reasons.append("malformed:asset_class")
    if venue and venue not in VENUES:
        reasons.append("malformed:venue")
    if asset_class in VENUE_FOR_CLASS and venue and VENUE_FOR_CLASS[asset_class] != venue:
        reasons.append("malformed:venue_does_not_match_asset_class")
    if direction and direction not in DIRECTIONS:
        reasons.append("malformed:direction")
    if venue == "hyperliquid" or asset_class in {"perp", "perpetual"}:
        reasons.append("malformed:hyperliquid_execution_not_used")

    entry = _money(data, "entry", reasons)
    size = _money(data, "size", reasons)
    estimated = _money(data, "max_estimated_loss", reasons)
    stop = _optional_money(data, "stop_loss", reasons)
    take_profit = _optional_money(data, "take_profit", reasons)
    if size is not None and size <= 0:
        reasons.append("malformed:size")
    if entry is not None and entry <= 0:
        reasons.append("malformed:entry")
    if estimated is not None and estimated <= 0:
        reasons.append("malformed:max_estimated_loss")
    if "stop_loss" not in data or data.get("stop_loss") in (None, ""):
        reasons.append("rejected:missing_stop_loss")
    if stop is not None and entry is not None and direction in DIRECTIONS:
        if direction == "buy" and stop >= entry:
            reasons.append("rejected:invalid_stop_loss")
        if direction == "sell" and stop <= entry:
            reasons.append("rejected:invalid_stop_loss")
    if take_profit is not None and entry is not None and direction in DIRECTIONS:
        if direction == "buy" and take_profit <= entry:
            reasons.append("malformed:take_profit")
        if direction == "sell" and take_profit >= entry:
            reasons.append("malformed:take_profit")

    data_timestamp = _time(data, "data_timestamp", reasons)
    expiry = _time(data, "expiry", reasons)
    if expiry is not None and expiry <= now:
        reasons.append("rejected:expired")
    if data_timestamp is not None and data_timestamp > now:
        reasons.append("rejected:data_timestamp_in_future")

    claimed_shariah = data.get("shariah_result")
    claimed_risk = data.get("risk_result")
    if claimed_shariah is not None and not isinstance(claimed_shariah, str):
        reasons.append("malformed:shariah_result")
        claimed_shariah = None
    if claimed_risk is not None and not isinstance(claimed_risk, str):
        reasons.append("malformed:risk_result")
        claimed_risk = None

    # Unique reasons, stable order.
    deduped = tuple(dict.fromkeys(reasons))
    if deduped or None in (entry, size, estimated, stop, data_timestamp, expiry):
        return ParseResult(None, deduped, proposal_id or None, idempotency_id or None)
    proposal = TradeProposal(
        proposal_id=proposal_id,
        idempotency_id=idempotency_id,
        instrument=instrument,
        asset_class=asset_class,
        venue=venue,
        contract_type=contract_type,
        direction=direction,
        entry=entry,
        stop_loss=stop,
        take_profit=take_profit,
        size=size,
        max_estimated_loss=estimated,
        data_source=data_source,
        data_timestamp=data_timestamp,
        strategy=strategy,
        evidence=evidence,
        expiry=expiry,
        claimed_shariah_result=claimed_shariah,
        claimed_risk_result=claimed_risk,
    )
    return ParseResult(proposal, (), proposal.proposal_id, proposal.idempotency_id)


def _idempotency_ok(value: str) -> bool:
    if len(value) > 36:
        return False
    return all(char.isalnum() or char in "-_" for char in value)


def _money(data: dict, field: str, reasons: list[str]) -> Decimal | None:
    if field not in data or data[field] in (None, ""):
        return None
    try:
        return parse_decimal(data[field], field)
    except ValueError:
        reasons.append(f"malformed:{field}")
        return None


def _optional_money(data: dict, field: str, reasons: list[str]) -> Decimal | None:
    if field not in data or data[field] in (None, ""):
        return None
    return _money(data, field, reasons)


def _time(data: dict, field: str, reasons: list[str]) -> datetime | None:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_utc(value, field)
    except ValueError:
        reasons.append(f"malformed:{field}")
        return None
