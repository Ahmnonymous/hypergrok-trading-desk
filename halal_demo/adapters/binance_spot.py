"""Binance Spot testnet shaped adapter.

Public spot testnet host is https://testnet.binance.vision.
This module does not call it, and it does not call mainnet, futures, margin,
or lending endpoints. Fixtures must say whether their prices are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from halal_demo.adapters.book import PreparedOrder, SimulatedBook
from halal_demo.adapters.models import Verification
from halal_demo.demo_guard import LOCAL_ENDPOINT, LOCAL_TRANSPORT, DestinationProof, refuse_network
from halal_demo.health import ComponentHealth
from halal_demo.risk import AccountState, CostInputs
from halal_demo.schema import TradeProposal
from halal_demo.shariah import InstrumentFacts

FUTURES_HOSTS = ("fapi.binance.com", "dapi.binance.com", "testnet.binancefuture.com")


def open_binance_http(*_args, **_kwargs):
    refuse_network("Binance HTTP")


def _on_step(value: Decimal, step: Decimal) -> bool:
    if step <= 0:
        return False
    units = value / step
    return units == units.to_integral_value()


@dataclass
class SimulatedBinanceSpot:
    venue: str = "binance_spot_testnet"
    account_type: str = "testnet"
    transport: str = "local_simulator"
    endpoint_label: str = LOCAL_ENDPOINT
    configured_host: str = "local-simulator"
    equity: Decimal | None = None
    currency: str = "USD"
    realized_pnl_today: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    as_of: datetime | None = None
    exchange_info: dict | None = None
    quotes: dict = field(default_factory=dict)
    specs: dict = field(default_factory=dict)
    sessions_open: dict = field(default_factory=dict)
    book: SimulatedBook = field(default_factory=SimulatedBook)
    healthy: bool = True

    def health(self) -> ComponentHealth:
        if not self.healthy or not self.exchange_info or self.equity is None:
            return ComponentHealth(self.venue, False, "exchangeInfo or account unavailable")
        label = self.exchange_info.get("label")
        if label not in {"synthetic", "offline_fixture"}:
            return ComponentHealth(self.venue, False, "exchangeInfo is not an offline fixture")
        return ComponentHealth(self.venue, True, f"local simulator, data label {label}")

    def destination_proof(self) -> DestinationProof:
        host = self.configured_host.lower()
        networkish = host not in {"local-simulator", LOCAL_ENDPOINT} or self.transport != LOCAL_TRANSPORT
        if any(name in host for name in FUTURES_HOSTS) or "fapi" in host:
            account_type = "live"
            transport = "network"
        elif networkish:
            account_type = "live" if "api.binance.com" in host else self.account_type
            transport = "network"
        else:
            account_type = self.account_type
            transport = LOCAL_TRANSPORT
        return DestinationProof(
            venue=self.venue,
            account_type=account_type,
            transport=transport,
            network_orders_enabled=transport != LOCAL_TRANSPORT,
            endpoint_label=LOCAL_ENDPOINT if transport == LOCAL_TRANSPORT else host,
            proof_source="adapter_configuration",
            trade_mode_name=account_type if account_type in {"demo", "paper", "testnet"} else account_type,
            detail="spot testnet shape, local simulator" if transport == LOCAL_TRANSPORT else "network host refused",
        )

    def account_state(self) -> AccountState:
        return AccountState(
            self.equity,
            self.currency,
            self.realized_pnl_today,
            self.unrealized_pnl,
            self.as_of,
            "binance_spot_simulator",
        )

    def symbol_row(self, symbol: str) -> dict | None:
        if not self.exchange_info:
            return None
        if self.exchange_info.get("label") not in {"synthetic", "offline_fixture"}:
            return None
        for row in self.exchange_info.get("symbols", []):
            if row.get("symbol") == symbol.upper():
                return row
        return None

    def verify(self, proposal: TradeProposal) -> Verification:
        row = self.symbol_row(proposal.instrument)
        quote = self.quotes.get(proposal.instrument.upper())
        spec = self.specs.get(proposal.instrument.upper())
        if row is None or quote is None or spec is None:
            return Verification(False, ("api_unavailable",), None, None, self.destination_proof(), None)
        reasons: list[str] = []
        if row.get("status") != "TRADING" or row.get("isSpotTradingAllowed") is not True:
            reasons.append("symbol_not_spot_trading")
        permissions = {str(item).upper() for item in row.get("permissions", [])}
        if permissions & {"LEVERAGED", "MARGIN"} and "SPOT" not in permissions:
            reasons.append("margin_or_leveraged_permissions")
        if self.sessions_open.get(proposal.instrument.upper()) is not True:
            reasons.append("trading_hours_closed_or_unknown")
        facts = self._facts(row, quote)
        if facts.contract_type != proposal.contract_type:
            reasons.append("proposal_contract_type_mismatch")
        if proposal.asset_class != "crypto":
            reasons.append("asset_class_mismatch")
        costs = self._costs(spec, quote)
        if costs is None:
            reasons.append("incomplete_contract_spec")
        filters = _filter_map(row)
        if not {"PRICE_FILTER", "LOT_SIZE"} <= set(filters) or not ({"MIN_NOTIONAL", "NOTIONAL"} & set(filters)):
            reasons.append("missing_exchange_filters")
        return Verification(not reasons, tuple(reasons), facts, costs, self.destination_proof(), True)

    def prepare(self, proposal: TradeProposal, costs: CostInputs):
        row = self.symbol_row(proposal.instrument)
        if row is None:
            return None, ("api_unavailable",)
        filters = _filter_map(row)
        price_filter = filters.get("PRICE_FILTER")
        lot_filter = filters.get("LOT_SIZE")
        notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
        if not price_filter or not lot_filter or not notional_filter:
            return None, ("missing_exchange_filters",)
        tick = Decimal(price_filter["tickSize"])
        step = Decimal(lot_filter["stepSize"])
        minimum = Decimal(notional_filter.get("minNotional", notional_filter.get("notional")))
        if not _on_step(proposal.entry, tick):
            return None, ("price_precision",)
        if not _on_step(proposal.size, step):
            return None, ("qty_precision",)
        if proposal.size < Decimal(lot_filter["minQty"]) or proposal.size > Decimal(lot_filter["maxQty"]):
            return None, ("qty_bounds",)
        if proposal.entry * proposal.size < minimum:
            return None, ("min_notional",)
        if proposal.stop_loss is None or not _on_step(proposal.stop_loss, tick):
            return None, ("stop_precision",)
        return PreparedOrder(
            proposal.proposal_id,
            proposal.idempotency_id,
            self.venue,
            proposal.instrument.upper(),
            proposal.direction,
            "LIMIT",
            proposal.entry,
            proposal.stop_loss,
            proposal.take_profit,
            proposal.size,
            "synthetic",
            False,
        ), ()

    def simulated_submit(self, order: PreparedOrder):
        host = self.configured_host.lower()
        if self.transport != LOCAL_TRANSPORT or any(name in host for name in ("binance.com", "binance.vision", "binancefuture")):
            refuse_network("binance order")
        if order.order_type != "LIMIT":
            return {"status": "rejected", "created": False, "order": None}
        return self.book.place(order)

    def read_order(self, idempotency_id: str):
        return self.book.read(idempotency_id)

    def cancel_unfilled(self) -> list[str]:
        return self.book.cancel_unfilled()

    def futures_create_order(self, *_args, **_kwargs):
        raise RuntimeError("futures orders are rejected by this adapter")

    def margin_borrow(self, *_args, **_kwargs):
        raise RuntimeError("margin and lending are rejected by this adapter")

    def _facts(self, row: dict, quote: dict) -> InstrumentFacts:
        permissions = {str(item).upper() for item in row.get("permissions", [])}
        margin_flag = row.get("isMarginTradingAllowed") is True
        if row.get("contractType") in {"PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"}:
            contract = "perpetual" if row.get("contractType") == "PERPETUAL" else "futures"
            leverage = "leveraged"
        elif "SPOT" in permissions and row.get("isSpotTradingAllowed") is True and not margin_flag:
            contract = "spot"
            leverage = "none"
        elif margin_flag:
            contract = "spot"
            leverage = "unknown"
        else:
            contract = "unknown"
            leverage = "unknown"
        label = quote.get("label") if quote.get("label") in {"synthetic", "offline_fixture"} else "rejected"
        source_ok = row.get("annotation_source") in {"fixture", "adviser_evidence"}
        return InstrumentFacts(
            instrument=row["symbol"],
            asset_class="crypto",
            venue=self.venue,
            contract_type=contract,
            leverage_class=leverage,
            swap_state="disabled" if row.get("swap_state") == "disabled" else "unknown",
            interest_bearing="no" if row.get("interest_bearing") == "no" else "unknown",
            ownership=row.get("ownership_annotation") if source_ok else None,
            settlement=row.get("settlement_annotation") if source_ok else None,
            business_activity=None,
            business_activity_verified=False,
            financials_verified=False,
            data_verified=bool(source_ok and label != "rejected" and row.get("data_verified") is True),
            market_data_label=label,
            gold_symbol=False,
            contract_structure_identified=contract == "spot",
            source="binance_spot_simulator_exchangeInfo",
            quoted_at=quote.get("time"),
        )

    def _costs(self, spec: dict, quote: dict) -> CostInputs | None:
        try:
            bid = Decimal(str(quote["bid"]))
            ask = Decimal(str(quote["ask"]))
            return CostInputs(
                bid=bid,
                ask=ask,
                spread=ask - bid,
                slippage=Decimal(str(spec["slippage"])),
                fee_per_side_account=Decimal(str(spec["fee_per_side_account"])),
                tick_size=Decimal(str(spec["tick_size"])),
                tick_value_account=Decimal(str(spec["tick_value_account"])),
                contract_size=Decimal(str(spec["contract_size"])),
                fx_rate_to_account=Decimal(str(spec["fx_rate_to_account"])),
                tick_value_currency=str(spec["currency"]),
                profit_currency=str(spec["currency"]),
                volume_step=Decimal(str(spec["volume_step"])),
                volume_min=Decimal(str(spec["volume_min"])),
                volume_max=Decimal(str(spec["volume_max"])),
                stop_loss_supported=True,
                quoted_at=quote["time"],
            )
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None


def _filter_map(row: dict) -> dict:
    found = {}
    for item in row.get("filters", []):
        if isinstance(item, dict) and item.get("filterType"):
            found[item["filterType"]] = item
    return found
