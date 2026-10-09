"""Alpaca paper-trading shaped provider.

Alpaca offers a real paper account. Paper HTTP is `paper-api.alpaca.markets`.
Live HTTP is `api.alpaca.markets`. This class does not call either host.
See https://docs.alpaca.markets/docs/paper-trading
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


class StockPaperProvider:
    """Interface a real paper-trading client would implement. No network here."""

    def get_account(self):
        raise NotImplementedError

    def get_asset(self, symbol: str):
        raise NotImplementedError

    def get_latest_quote(self, symbol: str):
        raise NotImplementedError

    def get_bars(self, symbol: str):
        raise NotImplementedError

    def list_orders(self):
        raise NotImplementedError

    def list_positions(self):
        raise NotImplementedError


def open_alpaca_http(*_args, **_kwargs):
    refuse_network("Alpaca paper or live HTTP")


@dataclass
class SimulatedAlpacaPaper(StockPaperProvider):
    venue: str = "alpaca_paper"
    account_type: str = "paper"
    transport: str = "local_simulator"
    endpoint_label: str = LOCAL_ENDPOINT
    currency: str = "USD"
    equity: Decimal | None = None
    cash: Decimal | None = None
    multiplier: str | None = None
    realized_pnl_today: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    as_of: datetime | None = None
    assets: dict = field(default_factory=dict)
    quotes: dict = field(default_factory=dict)
    specs: dict = field(default_factory=dict)
    bars: dict = field(default_factory=dict)
    sessions_open: dict = field(default_factory=dict)
    book: SimulatedBook = field(default_factory=SimulatedBook)
    healthy: bool = True

    def get_account(self):
        return {
            "account_type": self.account_type,
            "currency": self.currency,
            "equity": self.equity,
            "multiplier": self.multiplier,
            "status": "ACTIVE",
        }

    def get_asset(self, symbol: str):
        return self.assets.get(symbol)

    def get_latest_quote(self, symbol: str):
        return self.quotes.get(symbol)

    def get_bars(self, symbol: str):
        payload = self.bars.get(symbol)
        if not payload:
            return None
        if payload.get("label") not in {"synthetic", "offline_fixture"}:
            return None
        return payload

    def list_orders(self):
        return tuple(self.book.orders.values())

    def list_positions(self):
        return tuple(order for order in self.book.orders.values() if order.status == "filled")

    def health(self) -> ComponentHealth:
        if not self.healthy or self.get_account()["equity"] is None:
            return ComponentHealth("alpaca_paper", False, "paper account snapshot unavailable")
        return ComponentHealth("alpaca_paper", True, "local paper simulator")

    def destination_proof(self) -> DestinationProof:
        local = self.transport == LOCAL_TRANSPORT and self.endpoint_label == LOCAL_ENDPOINT
        return DestinationProof(
            venue=self.venue,
            account_type=self.account_type if local else self.account_type,
            transport=self.transport if local else "network",
            network_orders_enabled=not local,
            endpoint_label=self.endpoint_label if local else self.endpoint_label,
            proof_source="adapter_configuration",
            trade_mode_name=self.account_type if self.account_type in {"paper", "demo", "testnet"} else self.account_type,
            detail="Alpaca paper shape, local simulator" if local else "network endpoint refused",
        )

    def account_state(self) -> AccountState:
        return AccountState(
            self.equity,
            self.currency,
            self.realized_pnl_today,
            self.unrealized_pnl,
            self.as_of,
            "alpaca_paper_simulator",
        )

    def verify(self, proposal: TradeProposal) -> Verification:
        asset = self.get_asset(proposal.instrument)
        quote = self.get_latest_quote(proposal.instrument)
        spec = self.specs.get(proposal.instrument)
        if asset is None or quote is None or spec is None:
            return Verification(False, ("api_unavailable",), None, None, self.destination_proof(), None)
        reasons: list[str] = []
        if self.sessions_open.get(proposal.instrument) is not True:
            reasons.append("trading_hours_closed_or_unknown")
        facts = self._facts(asset, quote)
        if facts.contract_type != proposal.contract_type:
            reasons.append("proposal_contract_type_mismatch")
        if proposal.asset_class != "stock":
            reasons.append("asset_class_mismatch")
        costs = self._costs(spec, quote)
        if costs is None:
            reasons.append("incomplete_contract_spec")
        if quote.get("label") not in {"synthetic", "offline_fixture"}:
            reasons.append("market_data_label_rejected")
        return Verification(not reasons, tuple(reasons), facts, costs, self.destination_proof(), not reasons)

    def prepare(self, proposal: TradeProposal, costs: CostInputs):
        asset = self.get_asset(proposal.instrument)
        if asset is None:
            return None, ("api_unavailable",)
        if asset.get("fractionable") is not True and proposal.size != proposal.size.to_integral_value():
            return None, ("stock_qty_precision",)
        raw_increment = asset.get("price_increment")
        if raw_increment in (None, ""):
            return None, ("stock_price_precision",)
        increment = Decimal(str(raw_increment))
        if increment <= 0 or (proposal.entry / increment) != (proposal.entry / increment).to_integral_value():
            return None, ("stock_price_precision",)
        if proposal.stop_loss is None:
            return None, ("missing_stop_loss",)
        order = PreparedOrder(
            proposal.proposal_id,
            proposal.idempotency_id,
            self.venue,
            proposal.instrument,
            proposal.direction,
            "limit",
            proposal.entry,
            proposal.stop_loss,
            proposal.take_profit,
            proposal.size,
            "synthetic",
            False,
        )
        return order, ()

    def simulated_submit(self, order: PreparedOrder):
        if self.endpoint_label != LOCAL_ENDPOINT or self.transport != LOCAL_TRANSPORT:
            refuse_network("stock order")
        return self.book.place(order)

    def read_order(self, idempotency_id: str):
        return self.book.read(idempotency_id)

    def cancel_unfilled(self) -> list[str]:
        return self.book.cancel_unfilled()

    def _facts(self, asset: dict, quote: dict) -> InstrumentFacts:
        asset_class = asset.get("class")
        marginable = asset.get("marginable")
        shortable = asset.get("shortable")
        multiplier = self.multiplier
        if asset_class != "us_equity" or asset.get("tradable") is not True:
            contract = "unknown"
        elif marginable is False and shortable is False and multiplier == "1":
            contract = "cash_equity"
        elif marginable is True or (multiplier not in (None, "1")):
            contract = "margin"
        else:
            contract = "unknown"
        leverage = "none" if contract == "cash_equity" else ("leveraged" if contract == "margin" else "unknown")
        label = quote.get("label") if quote.get("label") in {"synthetic", "offline_fixture"} else "rejected"
        verified = bool(
            asset.get("business_activity_verified") is True
            and asset.get("data_verified") is True
            and asset.get("annotation_source") in {"fixture", "adviser_evidence"}
            and label != "rejected"
        )
        return InstrumentFacts(
            instrument=asset["symbol"],
            asset_class="stock",
            venue=self.venue,
            contract_type=contract,
            leverage_class=leverage,
            swap_state="disabled" if asset.get("swap_state") == "disabled" else "unknown",
            interest_bearing="no" if asset.get("interest_bearing") == "no" else "unknown",
            ownership=asset.get("ownership_annotation") if verified else None,
            settlement=asset.get("settlement_annotation") if verified else None,
            business_activity=asset.get("business_activity"),
            business_activity_verified=asset.get("business_activity_verified") is True,
            financials_verified=asset.get("financials_verified") is True,
            data_verified=verified,
            market_data_label=label,
            gold_symbol=False,
            contract_structure_identified=contract == "cash_equity",
            source="alpaca_paper_simulator_asset",
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
