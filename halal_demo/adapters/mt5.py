"""MetaTrader 5 shaped adapter.

The method names match the official MetaTrader5 Python package
(`account_info`, `symbol_info`, `symbol_info_tick`, `symbol_info_session`,
`order_check`, `order_send`, `orders_get`, `positions_get`, `last_error`).
This build only fills those methods on a local simulator. `order_send` on any
other object is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from halal_demo.adapters.book import PreparedOrder, SimulatedBook
from halal_demo.adapters.gold import gold_contract_type, is_gold_instrument
from halal_demo.adapters.mt5_constants import (
    ACCOUNT_TRADE_MODE_DEMO,
    ACCOUNT_TRADE_MODE_NAMES,
    CFD_CALC_MODES,
    FUTURES_CALC_MODES,
    ORDER_TYPE_BUY_LIMIT,
    ORDER_TYPE_SELL_LIMIT,
    SYMBOL_CALC_MODE_FOREX,
    SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE,
    SYMBOL_SWAP_MODE_DISABLED,
    TRADE_RETCODE_DONE,
    TRADE_RETCODE_INVALID,
    TRADE_RETCODE_INVALID_STOPS,
    TRADE_RETCODE_INVALID_VOLUME,
    TRADE_RETCODE_MARKET_CLOSED,
)
from halal_demo.demo_guard import LOCAL_ENDPOINT, LOCAL_TRANSPORT, DestinationProof, refuse_network
from halal_demo.risk import CostInputs
from halal_demo.schema import TradeProposal
from halal_demo.shariah import InstrumentFacts


def open_network_terminal(*_args, **_kwargs):
    """The official package would call MetaTrader5.initialize. This build does not."""
    refuse_network("MetaTrader5.initialize/login/order_send")


@dataclass
class SimulatedMT5Terminal:
    """In-memory stand-in with the official attribute names."""

    is_local_simulator: bool = True
    account: dict = field(default_factory=dict)
    symbols: dict = field(default_factory=dict)
    ticks: dict = field(default_factory=dict)
    sessions: dict = field(default_factory=dict)
    realized_pnl_today: Decimal | None = None
    book: SimulatedBook = field(default_factory=SimulatedBook)
    _last_error: tuple[int, str] = (1, "Success")

    def account_info(self):
        if not self.account:
            self._last_error = (1, "account unavailable")
            return None
        return SimpleNamespace(**self.account)

    def symbol_info(self, symbol: str):
        info = self.symbols.get(symbol)
        if info is None:
            self._last_error = (4301, "unknown symbol")
            return None
        return SimpleNamespace(**info)

    def symbol_info_tick(self, symbol: str):
        tick = self.ticks.get(symbol)
        if tick is None:
            self._last_error = (1, "tick unavailable")
            return None
        return SimpleNamespace(**tick)

    def symbol_info_session(self, symbol: str, day_of_week: int, session_index: int):
        rows = self.sessions.get(symbol, {}).get(day_of_week, [])
        if session_index >= len(rows):
            return None
        start, end = rows[session_index]
        return SimpleNamespace(**{"from": start, "to": end})

    def daily_realized_pnl(self):
        return self.realized_pnl_today

    def order_check(self, request: dict):
        return check_mt5_request(self, request)

    def order_send(self, request: dict):
        if not self.is_local_simulator:
            refuse_network("order_send")
        checked = self.order_check(request)
        if checked.retcode != TRADE_RETCODE_DONE:
            self._last_error = (checked.retcode, checked.comment)
            return checked
        prepared = PreparedOrder(
            proposal_id=str(request.get("comment") or ""),
            idempotency_id=str(request["magic_idem"]),
            venue="mt5",
            instrument=request["symbol"],
            side="buy" if request["type"] == ORDER_TYPE_BUY_LIMIT else "sell",
            order_type="limit",
            price=Decimal(str(request["price"])),
            stop_loss=Decimal(str(request["sl"])),
            take_profit=Decimal(str(request["tp"])) if request.get("tp") else None,
            quantity=Decimal(str(request["volume"])),
            market_data_label=request.get("market_data_label", "synthetic"),
            network_send=False,
        )
        result = self.book.place(prepared)
        self._last_error = (1, "Success")
        return SimpleNamespace(retcode=TRADE_RETCODE_DONE, comment="simulator", order=result["order"], request_id=1)

    def orders_get(self, **kwargs):
        idem = kwargs.get("idempotency_id")
        if idem:
            order = self.book.read(idem)
            return () if order is None else (order,)
        return tuple(self.book.orders.values())

    def positions_get(self, **_kwargs):
        return tuple(order for order in self.book.orders.values() if order.status == "filled")

    def last_error(self):
        return self._last_error


class GuardedMT5Terminal:
    """Wraps a terminal. Network terminals cannot send."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def order_send(self, request):
        if not getattr(self.inner, "is_local_simulator", False):
            refuse_network("order_send")
        return self.inner.order_send(request)


def check_mt5_request(terminal: SimulatedMT5Terminal, request: dict):
    symbol = request.get("symbol")
    info = terminal.symbol_info(symbol) if symbol else None
    if info is None:
        return SimpleNamespace(retcode=TRADE_RETCODE_INVALID, comment="unknown symbol")
    if not session_is_open(terminal, symbol, request.get("now")):
        return SimpleNamespace(retcode=TRADE_RETCODE_MARKET_CLOSED, comment="market closed or hours unknown")
    volume = Decimal(str(request["volume"]))
    step = Decimal(str(info.volume_step))
    if step <= 0 or (volume / step) != (volume / step).to_integral_value():
        return SimpleNamespace(retcode=TRADE_RETCODE_INVALID_VOLUME, comment="volume step")
    if volume < Decimal(str(info.volume_min)) or volume > Decimal(str(info.volume_max)):
        return SimpleNamespace(retcode=TRADE_RETCODE_INVALID_VOLUME, comment="volume bounds")
    if request.get("sl") in (None, 0):
        return SimpleNamespace(retcode=TRADE_RETCODE_INVALID_STOPS, comment="stop required")
    return SimpleNamespace(retcode=TRADE_RETCODE_DONE, comment="checked")


def session_is_open(terminal: SimulatedMT5Terminal, symbol: str, now: datetime | None) -> bool:
    if now is None or symbol not in terminal.sessions:
        return False
    # MQL5 ENUM_DAY_OF_WEEK: Sunday = 0. Python Monday = 0.
    mt5_day = (now.weekday() + 1) % 7
    minute = now.hour * 60 + now.minute
    index = 0
    saw = False
    while True:
        session = terminal.symbol_info_session(symbol, mt5_day, index)
        if session is None:
            break
        saw = True
        if session.__dict__["from"] <= minute < session.to:
            return True
        index += 1
    return False if saw else False


class MT5Adapter:
    venue = "mt5"

    def __init__(self, terminal: SimulatedMT5Terminal):
        if not getattr(terminal, "is_local_simulator", False):
            refuse_network("MT5Adapter")
        self.terminal = GuardedMT5Terminal(terminal)

    def health(self):
        from halal_demo.health import ComponentHealth

        info = self.terminal.account_info()
        if info is None:
            return ComponentHealth("mt5", False, "account_info unavailable")
        return ComponentHealth("mt5", True, "local simulator account_info present")

    def account_state(self):
        from decimal import Decimal

        from halal_demo.risk import AccountState

        info = self.terminal.account_info()
        if info is None:
            return AccountState(None, None, None, None, None, "mt5")

        def money(name):
            value = getattr(info, name, None)
            if value is None:
                return None
            return Decimal(str(value))

        return AccountState(
            money("equity"),
            getattr(info, "currency", None),
            self.terminal.daily_realized_pnl(),
            money("profit"),
            getattr(info, "as_of", None),
            "mt5_simulator",
        )

    def destination_proof(self) -> DestinationProof:
        info = self.terminal.account_info()
        if info is None:
            return DestinationProof(
                "mt5", "unknown", "unknown", True, "unknown", "adapter_configuration", "unknown",
                "account_info unavailable",
            )
        mode = ACCOUNT_TRADE_MODE_NAMES.get(info.trade_mode, "unknown")
        simulator = bool(getattr(self.terminal, "is_local_simulator", False))
        return DestinationProof(
            venue="mt5",
            account_type="demo" if mode == "demo" and simulator else mode,
            transport=LOCAL_TRANSPORT if simulator else "network",
            network_orders_enabled=not simulator,
            endpoint_label=LOCAL_ENDPOINT if simulator else str(getattr(info, "server", "network")),
            proof_source="adapter_configuration",
            trade_mode_name=mode if simulator else mode,
            detail="local simulator" if simulator else "network terminal refused",
        )

    def verify(self, proposal: TradeProposal):
        from halal_demo.adapters.models import Verification

        info = self.terminal.symbol_info(proposal.instrument)
        tick = self.terminal.symbol_info_tick(proposal.instrument)
        account = self.terminal.account_info()
        if info is None or tick is None or account is None:
            return Verification(False, ("api_unavailable",), None, None, self.destination_proof(), None)
        reasons = []
        if not session_is_open(self.terminal, proposal.instrument, tick.time):
            reasons.append("trading_hours_closed_or_unknown")
        facts, costs, class_reasons = facts_from_mt5(info, tick, account)
        reasons.extend(class_reasons)
        if proposal.contract_type != facts.contract_type:
            reasons.append("proposal_contract_type_mismatch")
        expected_class = "gold" if facts.gold_symbol else "forex"
        if proposal.asset_class != expected_class:
            reasons.append("asset_class_mismatch")
        hours = "trading_hours_closed_or_unknown" not in reasons
        return Verification(
            not reasons,
            tuple(reasons),
            facts,
            costs,
            self.destination_proof(),
            hours,
        )

    def prepare(self, proposal: TradeProposal, costs: CostInputs) -> tuple[PreparedOrder | None, tuple[str, ...]]:
        request = {
            "symbol": proposal.instrument,
            "volume": proposal.size,
            "type": ORDER_TYPE_BUY_LIMIT if proposal.direction == "buy" else ORDER_TYPE_SELL_LIMIT,
            "price": proposal.entry,
            "sl": proposal.stop_loss,
            "tp": proposal.take_profit or 0,
            "now": costs.quoted_at,
            "magic_idem": proposal.idempotency_id,
            "comment": proposal.proposal_id,
            "market_data_label": "synthetic",
        }
        checked = self.terminal.order_check(request)
        if checked.retcode != TRADE_RETCODE_DONE:
            return None, (f"mt5_order_check:{checked.retcode}:{checked.comment}",)
        if proposal.stop_loss is None:
            return None, ("missing_stop_loss",)
        return PreparedOrder(
            proposal.proposal_id,
            proposal.idempotency_id,
            "mt5",
            proposal.instrument,
            proposal.direction,
            "limit",
            proposal.entry,
            proposal.stop_loss,
            proposal.take_profit,
            proposal.size,
            "synthetic",
            False,
        ), ()

    def simulated_submit(self, order: PreparedOrder):
        if self.terminal.symbol_info(order.instrument) is None:
            return {"status": "unavailable", "created": False, "order": None}
        if self.terminal.book.mode == "unavailable":
            return {"status": "unavailable", "created": False, "order": None}
        return self.terminal.book.place(order)

    def read_order(self, idempotency_id: str):
        found = self.terminal.orders_get(idempotency_id=idempotency_id)
        return found[0] if found else None

    def cancel_unfilled(self) -> list[str]:
        return self.terminal.book.cancel_unfilled()


def facts_from_mt5(info, tick, account) -> tuple[InstrumentFacts, CostInputs | None, list[str]]:
    reasons: list[str] = []
    gold = is_gold_instrument(info.name, getattr(info, "path", ""))
    mode = info.trade_calc_mode
    contract = "unknown"
    leverage = "unknown"
    structure_identified = False
    if gold:
        contract = gold_contract_type(mode)
        structure_identified = False
        if contract in {"cfd", "futures", "leveraged_forex"}:
            leverage = "leveraged"
        elif mode == SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE:
            leverage = _cash_leverage(info, account)
    elif mode == SYMBOL_CALC_MODE_FOREX:
        contract = "leveraged_forex"
        leverage = "leveraged"
    elif mode in CFD_CALC_MODES:
        contract = "cfd"
        leverage = "leveraged"
    elif mode in FUTURES_CALC_MODES:
        contract = "futures"
        leverage = "leveraged"
    elif mode == SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE:
        contract = "forex_no_account_leverage"
        leverage = _cash_leverage(info, account)
        structure_identified = True
    else:
        contract = "unknown"
        reasons.append("unmapped_calc_mode")
    swap_state, interest = _swaps(info)
    if leverage == "unknown" and not gold:
        reasons.append("leverage_unknown")
    ownership = _annotation(info, "ownership_annotation")
    settlement = _annotation(info, "settlement_annotation")
    label = getattr(tick, "market_data_label", None)
    if label not in {"synthetic", "offline_fixture"}:
        reasons.append("market_data_label_rejected")
        label = label or "missing"
    verified = not reasons and _spec_complete(info)
    facts = InstrumentFacts(
        instrument=info.name,
        asset_class="gold" if gold else "forex",
        venue="mt5",
        contract_type=contract,
        leverage_class=leverage if not (gold and contract == "unidentified_gold_otc" and leverage == "unknown") else leverage,
        swap_state=swap_state,
        interest_bearing=interest,
        ownership=ownership,
        settlement=settlement,
        business_activity=None,
        business_activity_verified=False,
        financials_verified=False,
        data_verified=verified and ownership is not None and settlement is not None and label in {"synthetic", "offline_fixture"},
        market_data_label=label if label in {"synthetic", "offline_fixture"} else "rejected",
        gold_symbol=gold,
        contract_structure_identified=structure_identified and not gold,
        source="mt5_simulator_symbol_info",
        quoted_at=getattr(tick, "time", None),
    )
    costs = _costs(info, tick)
    if costs is None:
        reasons.append("incomplete_contract_spec")
    return facts, costs, reasons


def _cash_leverage(info, account) -> str:
    leverage = getattr(account, "leverage", None)
    initial = getattr(info, "margin_initial", None)
    maintenance = getattr(info, "margin_maintenance", None)
    if None in (leverage, initial, maintenance):
        return "unknown"
    if leverage == 1 and initial == 0 and maintenance == 0:
        return "none"
    if leverage > 1 or initial > 0 or maintenance > 0:
        return "leveraged"
    return "unknown"


def _swaps(info) -> tuple[str, str]:
    mode = getattr(info, "swap_mode", None)
    long = getattr(info, "swap_long", None)
    short = getattr(info, "swap_short", None)
    if None in (mode, long, short):
        return "unknown", "unknown"
    if mode != SYMBOL_SWAP_MODE_DISABLED or long != 0 or short != 0:
        return "enabled", "yes"
    return "disabled", "no"


def _annotation(info, field: str):
    if getattr(info, "annotation_source", None) not in {"fixture", "adviser_evidence"}:
        return None
    value = getattr(info, field, None)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _spec_complete(info) -> bool:
    needed = (
        "trade_tick_size",
        "trade_tick_value",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "currency_profit",
    )
    return all(getattr(info, name, None) is not None for name in needed)


def _costs(info, tick) -> CostInputs | None:
    try:
        bid = Decimal(str(tick.bid))
        ask = Decimal(str(tick.ask))
        spread = ask - bid
        return CostInputs(
            bid=bid,
            ask=ask,
            spread=spread,
            slippage=Decimal(str(info.slippage)),
            fee_per_side_account=Decimal(str(info.fee_per_side_account)),
            tick_size=Decimal(str(info.trade_tick_size)),
            tick_value_account=Decimal(str(info.trade_tick_value)),
            contract_size=Decimal(str(info.trade_contract_size)),
            fx_rate_to_account=Decimal(str(info.fx_rate_to_account)),
            tick_value_currency=str(info.currency_profit),
            profit_currency=str(info.currency_profit),
            volume_step=Decimal(str(info.volume_step)),
            volume_min=Decimal(str(info.volume_min)),
            volume_max=Decimal(str(info.volume_max)),
            stop_loss_supported=True,
            quoted_at=tick.time,
        )
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        return None
