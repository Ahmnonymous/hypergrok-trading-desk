"""Deterministic risk gate shared by every adapter.

Limits come from a config object. A proposal cannot change them. Missing
tick value, contract size, FX, spread, fees, or daily PnL blocks the trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from halal_demo.config import require_int, require_percent, require_text, require_time
from halal_demo.errors import ConfigError
from halal_demo.schema import TradeProposal

REJECT = "REJECT"


@dataclass(frozen=True)
class RiskLimits:
    rule_version: str
    account_currency: str
    max_risk_per_trade_percent: Decimal
    daily_loss_stop_percent: Decimal
    max_open_risk_percent: Decimal
    max_open_positions: int
    max_price_age_seconds: int
    max_attempts_per_proposal: int
    limits_expiry: datetime
    correlation_clusters: dict[str, tuple[str, ...]]

    @classmethod
    def from_dict(cls, data: dict) -> "RiskLimits":
        errors: list[str] = []
        version = require_text(data, "rule_version", errors)
        currency = require_text(data, "account_currency", errors)
        per_trade = require_percent(data, "max_risk_per_trade_percent", errors)
        daily = require_percent(data, "daily_loss_stop_percent", errors)
        open_risk = require_percent(data, "max_open_risk_percent", errors)
        positions = require_int(data, "max_open_positions", errors)
        age = require_int(data, "max_price_age_seconds", errors)
        attempts = require_int(data, "max_attempts_per_proposal", errors)
        expiry = require_time(data, "limits_expiry", errors)
        clusters = data.get("correlation_clusters")
        parsed: dict[str, tuple[str, ...]] = {}
        if not isinstance(clusters, dict):
            errors.append("missing:correlation_clusters")
        else:
            for name, members in clusters.items():
                if not isinstance(members, list) or not all(isinstance(item, str) and item for item in members):
                    errors.append(f"invalid:correlation_clusters.{name}")
                    continue
                parsed[str(name)] = tuple(item.upper() for item in members)
        if attempts != 1:
            errors.append("max_attempts_per_proposal must be 1 in this build")
        if errors or None in (per_trade, daily, open_risk, positions, age, attempts, expiry):
            raise ConfigError(errors)
        assert per_trade and daily and open_risk and positions and age and attempts and expiry
        return cls(
            version,
            currency,
            per_trade,
            daily,
            open_risk,
            positions,
            age,
            attempts,
            expiry,
            parsed,
        )

    def fraction(self, percent: Decimal) -> Decimal:
        return percent / Decimal(100)


def refuse_agent_override(limits: RiskLimits, proposed: dict | None) -> tuple[RiskLimits, str]:
    """Agents may suggest numbers. The object that is enforced does not change."""
    if proposed:
        return limits, "agent_override_ignored"
    return limits, "no_override"


@dataclass(frozen=True)
class CostInputs:
    bid: Decimal
    ask: Decimal
    spread: Decimal
    slippage: Decimal
    fee_per_side_account: Decimal
    tick_size: Decimal
    tick_value_account: Decimal
    contract_size: Decimal
    fx_rate_to_account: Decimal
    tick_value_currency: str
    profit_currency: str
    volume_step: Decimal
    volume_min: Decimal
    volume_max: Decimal
    stop_loss_supported: bool
    quoted_at: datetime


@dataclass
class OpenExposure:
    proposal_id: str
    instrument: str
    venue: str
    worst_case_loss_account: Decimal
    size: Decimal


@dataclass
class AccountState:
    equity: Decimal | None
    currency: str | None
    realized_pnl_today: Decimal | None
    unrealized_pnl: Decimal | None
    as_of: datetime | None
    source: str


@dataclass
class PositionBook:
    positions: list[OpenExposure] = field(default_factory=list)

    def add(self, position: OpenExposure) -> None:
        self.positions.append(position)

    def __len__(self) -> int:
        return len(self.positions)


@dataclass(frozen=True)
class RiskDecision:
    status: str
    rule_version: str
    reasons: tuple[str, ...]
    worst_case_loss_account: Decimal | None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def cluster_for(limits: RiskLimits, instrument: str) -> str | None:
    symbol = instrument.upper()
    found = [name for name, members in limits.correlation_clusters.items() if symbol in members]
    if len(found) > 1:
        return "__ambiguous__"
    if not found:
        return None
    return found[0]


def evaluate_risk(
    proposal: TradeProposal,
    costs: CostInputs | None,
    limits: RiskLimits,
    account: AccountState,
    book: PositionBook,
    now: datetime,
    *,
    price_is_stale: bool = False,
    services_healthy: bool = False,
) -> RiskDecision:
    reasons: list[str] = []
    if limits.limits_expiry <= now:
        reasons.append("risk_limits_expired")
    if not services_healthy:
        reasons.append("unhealthy_services")
    if price_is_stale:
        reasons.append("stale_price")
    if account.equity is None or account.equity <= 0:
        reasons.append("missing:equity")
    if account.currency != limits.account_currency:
        reasons.append("missing_or_mismatch:account_currency")
    if account.realized_pnl_today is None:
        reasons.append("missing:realized_pnl_today")
    if account.unrealized_pnl is None:
        reasons.append("missing:unrealized_pnl")
    if account.as_of is None:
        reasons.append("missing:account_as_of")
    elif abs((now - account.as_of).total_seconds()) > limits.max_price_age_seconds:
        reasons.append("stale_account")
    if costs is None:
        reasons.append("missing:contract_spec")
        return _reject(limits, reasons, None)
    spec_reasons = _check_costs(costs, limits, now)
    reasons.extend(spec_reasons)
    if proposal.stop_loss is None or not costs.stop_loss_supported:
        reasons.append("missing_or_unsupported_stop_loss")
    loss = None
    if not spec_reasons and proposal.stop_loss is not None and costs.stop_loss_supported:
        try:
            loss = worst_case_loss(proposal, costs, limits.account_currency)
        except ValueError as exc:
            reasons.append(str(exc))
    if loss is not None and proposal.max_estimated_loss < loss:
        reasons.append("proposer_understated_loss")
    if account.equity is not None and loss is not None:
        cap = account.equity * limits.fraction(limits.max_risk_per_trade_percent)
        if loss > cap:
            reasons.append("excessive_risk")
    if (
        account.equity is not None
        and account.realized_pnl_today is not None
        and account.unrealized_pnl is not None
    ):
        pnl = account.realized_pnl_today + account.unrealized_pnl
        lost = -pnl if pnl < 0 else Decimal(0)
        stop = account.equity * limits.fraction(limits.daily_loss_stop_percent)
        if lost >= stop:
            reasons.append("daily_loss_stop")
    if len(book) >= limits.max_open_positions:
        reasons.append("position_limit")
    if loss is not None and account.equity is not None:
        group = cluster_for(limits, proposal.instrument)
        if group == "__ambiguous__":
            reasons.append("ambiguous_correlation_cluster")
        else:
            existing = Decimal(0)
            for position in book.positions:
                other = cluster_for(limits, position.instrument)
                if group is not None and other == group:
                    existing += position.worst_case_loss_account
                elif group is None and position.instrument.upper() == proposal.instrument.upper():
                    existing += position.worst_case_loss_account
            open_cap = account.equity * limits.fraction(limits.max_open_risk_percent)
            if existing + loss > open_cap:
                reasons.append("correlated_exposure_limit")
    if _size_off_step(proposal.size, costs):
        reasons.append("size_precision")
    if reasons:
        return _reject(limits, reasons, loss)
    return RiskDecision("PASS", limits.rule_version, ("within_limits",), loss)


def worst_case_loss(proposal: TradeProposal, costs: CostInputs, account_currency: str) -> Decimal:
    if costs.tick_value_currency != account_currency:
        raise ValueError("missing:tick_value_fx")
    if costs.fx_rate_to_account != 1 and costs.profit_currency == account_currency:
        raise ValueError("inconsistent:fx_rate")
    if costs.profit_currency != account_currency and costs.fx_rate_to_account <= 0:
        raise ValueError("missing:fx_rate")
    assert proposal.stop_loss is not None
    slip = costs.slippage
    spread = costs.spread
    if proposal.direction == "buy":
        worst_entry = proposal.entry + slip + spread
        worst_exit = proposal.stop_loss - slip
        price_diff = worst_entry - worst_exit
    else:
        worst_entry = proposal.entry - slip - spread
        worst_exit = proposal.stop_loss + slip
        price_diff = worst_exit - worst_entry
    if price_diff <= 0:
        raise ValueError("stop_does_not_cover_spread_and_slippage")
    if costs.tick_size <= 0 or costs.tick_value_account <= 0 or costs.contract_size <= 0:
        raise ValueError("missing:tick_or_contract")
    expected_tick = costs.contract_size * costs.tick_size * costs.fx_rate_to_account
    if expected_tick != costs.tick_value_account:
        raise ValueError("inconsistent:tick_value_and_contract_size")
    ticks = price_diff / costs.tick_size
    price_loss = ticks * costs.tick_value_account * proposal.size
    fees = costs.fee_per_side_account * 2 * proposal.size
    if fees < 0:
        raise ValueError("invalid:fees")
    return price_loss + fees


def _check_costs(costs: CostInputs, limits: RiskLimits, now: datetime) -> list[str]:
    reasons = []
    required = {
        "bid": costs.bid,
        "ask": costs.ask,
        "spread": costs.spread,
        "slippage": costs.slippage,
        "fee_per_side_account": costs.fee_per_side_account,
        "tick_size": costs.tick_size,
        "tick_value_account": costs.tick_value_account,
        "contract_size": costs.contract_size,
        "fx_rate_to_account": costs.fx_rate_to_account,
        "volume_step": costs.volume_step,
        "volume_min": costs.volume_min,
        "volume_max": costs.volume_max,
    }
    for name, value in required.items():
        if value is None:
            reasons.append(f"missing:{name}")
        elif name not in {"bid", "ask"} and value < 0:
            reasons.append(f"invalid:{name}")
    if costs.spread < 0 or (costs.ask - costs.bid) != costs.spread:
        reasons.append("inconsistent:spread")
    if costs.quoted_at is None:
        reasons.append("missing:quoted_at")
    elif now - costs.quoted_at > timedelta(seconds=limits.max_price_age_seconds):
        reasons.append("stale_price")
    if costs.quoted_at is not None and costs.quoted_at > now:
        reasons.append("quote_in_future")
    if not costs.tick_value_currency or not costs.profit_currency:
        reasons.append("missing:currency")
    return reasons


def _size_off_step(size: Decimal, costs: CostInputs) -> bool:
    if costs.volume_step <= 0:
        return True
    units = size / costs.volume_step
    if units != units.to_integral_value():
        return True
    if size < costs.volume_min or size > costs.volume_max:
        return True
    return False


def _reject(limits: RiskLimits, reasons: list[str], loss: Decimal | None) -> RiskDecision:
    return RiskDecision(REJECT, limits.rule_version, tuple(dict.fromkeys(reasons)), loss)
