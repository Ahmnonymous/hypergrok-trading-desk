"""Shared fixtures. Symbols here are synthetic. They are not approvals of real markets."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from halal_demo.adapters.binance_spot import SimulatedBinanceSpot
from halal_demo.adapters.mt5 import MT5Adapter, SimulatedMT5Terminal
from halal_demo.adapters.mt5_constants import (
    ACCOUNT_TRADE_MODE_DEMO,
    SYMBOL_CALC_MODE_CFD,
    SYMBOL_CALC_MODE_FOREX,
    SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE,
    SYMBOL_SWAP_MODE_DISABLED,
)
from halal_demo.config import RuntimeConfig, load_json
from halal_demo.pipeline import Desk
from halal_demo.risk import RiskLimits
from halal_demo.shariah import ShariahPolicy

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
QUOTE = datetime(2026, 10, 9, 11, 59, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def clock():
    from halal_demo.clock import FixedClock

    return FixedClock(NOW)


def risk_limits(**overrides) -> RiskLimits:
    data = load_json(ROOT / "config" / "risk.demo.json")
    data.update(overrides)
    return RiskLimits.from_dict(data)


def runtime(allow_test: bool = True) -> RuntimeConfig:
    return RuntimeConfig.from_dict(
        {
            "mode": "demo",
            "allow_network_orders": False,
            "transport": "local_simulator",
            "allow_offline_test_policy": allow_test,
        }
    )


def test_policy() -> ShariahPolicy:
    record = {
        "ownership": "fixture_cash_securities",
        "settlement": "fixture_t_plus_demo",
        "business_activity": "demo_permitted_activity",
        "financial_screen_decision": "recorded",
        "gold_structure_accepted": False,
        "evidence_note": "synthetic fixture for the software test, not a religious ruling",
    }
    return ShariahPolicy.from_dict(
        {
            "rule_version": "offline-test-2026-10-09",
            "reviewer": "OFFLINE_TEST_FIXTURE",
            "review_date": "2026-10-09",
            "expiry": "2026-12-31T00:00:00Z",
            "evidence_source": "unit test fixture",
            "decision_status": "recorded_for_offline_test_only",
            "offline_test_only": True,
            "accepted_ownership": ["fixture_cash_securities"],
            "accepted_settlement": ["fixture_t_plus_demo"],
            "accepted_business_activities": ["demo_permitted_activity"],
            "prohibited_business_activities": ["conventional_banking", "alcohol", "gambling"],
            "prohibited_instruments": ["BANCO"],
            "crypto_eligibility": [
                {"instrument": "DEMOCOINUSDT", "contract_type": "spot", "decision": "eligible"},
                {"instrument": "BTCUSDT", "contract_type": "spot", "decision": "ineligible"},
            ],
            "stock_financial_criteria": None,
            "approvals": [
                {"instrument": "DEMOHALAL", "asset_class": "stock", "venue": "alpaca_paper", "contract_type": "cash_equity", **record},
                {
                    "instrument": "DEMOCASH",
                    "asset_class": "forex",
                    "venue": "mt5",
                    "contract_type": "forex_no_account_leverage",
                    "ownership": "fixture_cash_securities",
                    "settlement": "fixture_t_plus_demo",
                    "financial_screen_decision": None,
                    "gold_structure_accepted": False,
                    "evidence_note": "synthetic cash unit, not a real FX contract and not a ruling",
                },
                {
                    "instrument": "DEMOCOINUSDT",
                    "asset_class": "crypto",
                    "venue": "binance_spot_testnet",
                    "contract_type": "spot",
                    "ownership": "fixture_cash_securities",
                    "settlement": "fixture_t_plus_demo",
                    "financial_screen_decision": None,
                    "gold_structure_accepted": False,
                    "evidence_note": "synthetic spot book, not a Binance listing and not a ruling",
                },
            ],
        }
    )


def proposal(**overrides) -> dict:
    body = {
        "proposal_id": "HD-20261009-01",
        "idempotency_id": "hd-20261009-01",
        "instrument": "DEMOHALAL",
        "asset_class": "stock",
        "venue": "alpaca_paper",
        "contract_type": "cash_equity",
        "direction": "buy",
        "entry": "100",
        "stop_loss": "99",
        "take_profit": "105",
        "size": "10",
        "max_estimated_loss": "250",
        "data_source": "offline fixture",
        "data_timestamp": "2026-10-09T11:59:00Z",
        "strategy": "manual demo",
        "evidence": "synthetic fixture, not a live market call",
        "expiry": "2026-10-09T12:30:00Z",
    }
    body.update(overrides)
    return body


def cash_spec(**overrides) -> dict:
    spec = {
        "slippage": "0",
        "fee_per_side_account": "0",
        "tick_size": "0.01",
        "tick_value_account": "0.01",
        "contract_size": "1",
        "fx_rate_to_account": "1",
        "currency": "USD",
        "volume_step": "1",
        "volume_min": "1",
        "volume_max": "100000",
    }
    spec.update(overrides)
    return spec


def stock_asset(symbol="DEMOHALAL", **overrides) -> dict:
    asset = {
        "symbol": symbol,
        "class": "us_equity",
        "tradable": True,
        "fractionable": False,
        "marginable": False,
        "shortable": False,
        "status": "active",
        "price_increment": "0.01",
        "business_activity": "demo_permitted_activity",
        "business_activity_verified": True,
        "financials_verified": True,
        "data_verified": True,
        "ownership_annotation": "fixture_cash_securities",
        "settlement_annotation": "fixture_t_plus_demo",
        "annotation_source": "fixture",
        "swap_state": "disabled",
        "interest_bearing": "no",
    }
    asset.update(overrides)
    return asset


def quote(when=QUOTE, bid="100", ask="100", label="synthetic") -> dict:
    return {"bid": bid, "ask": ask, "time": when, "label": label}


def paper(**overrides):
    from halal_demo.adapters.stock_paper import SimulatedAlpacaPaper

    adapter = SimulatedAlpacaPaper(
        equity=Decimal("100000"),
        cash=Decimal("100000"),
        multiplier="1",
        realized_pnl_today=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        as_of=NOW,
        assets={"DEMOHALAL": stock_asset()},
        quotes={"DEMOHALAL": quote()},
        specs={"DEMOHALAL": cash_spec()},
        sessions_open={"DEMOHALAL": True},
    )
    for key, value in overrides.items():
        setattr(adapter, key, value)
    return adapter


def mt5_symbol(name, calc_mode, **overrides) -> dict:
    info = {
        "name": name,
        "path": "Demo\\Cash",
        "trade_calc_mode": calc_mode,
        "swap_mode": SYMBOL_SWAP_MODE_DISABLED,
        "swap_long": 0,
        "swap_short": 0,
        "margin_initial": 0,
        "margin_maintenance": 0,
        "trade_tick_size": "0.01",
        "trade_tick_value": "0.01",
        "trade_contract_size": "1",
        "volume_min": "1",
        "volume_max": "100000",
        "volume_step": "1",
        "currency_profit": "USD",
        "fx_rate_to_account": "1",
        "slippage": "0",
        "fee_per_side_account": "0",
        "annotation_source": "fixture",
        "ownership_annotation": "fixture_cash_securities",
        "settlement_annotation": "fixture_t_plus_demo",
    }
    info.update(overrides)
    return info


def mt5_terminal(symbols: dict | None = None, trade_mode=ACCOUNT_TRADE_MODE_DEMO, **account_overrides):
    symbols = symbols or {"DEMOCASH": mt5_symbol("DEMOCASH", SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE)}
    sessions = {name: {day: [(0, 24 * 60)] for day in range(7)} for name in symbols}
    ticks = {name: {"bid": "100", "ask": "100", "time": QUOTE, "market_data_label": "synthetic"} for name in symbols}
    account = {
        "login": 1,
        "trade_mode": trade_mode,
        "leverage": 1,
        "currency": "USD",
        "equity": "100000",
        "profit": "0",
        "balance": "100000",
        "server": "local-simulator",
        "as_of": NOW,
    }
    account.update(account_overrides)
    return SimulatedMT5Terminal(
        account=account,
        symbols=symbols,
        ticks=ticks,
        sessions=sessions,
        realized_pnl_today=Decimal("0"),
    )


def mt5_adapter(**kwargs) -> MT5Adapter:
    return MT5Adapter(mt5_terminal(**kwargs))


def binance_symbol(symbol, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "status": "TRADING",
        "isSpotTradingAllowed": True,
        "isMarginTradingAllowed": False,
        "permissions": ["SPOT"],
        "data_verified": True,
        "annotation_source": "fixture",
        "ownership_annotation": "fixture_cash_securities",
        "settlement_annotation": "fixture_t_plus_demo",
        "swap_state": "disabled",
        "interest_bearing": "no",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01", "minPrice": "0.01", "maxPrice": "100000"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "100000"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
        ],
    }
    row.update(overrides)
    return row


def binance(**overrides) -> SimulatedBinanceSpot:
    info = {
        "label": "synthetic",
        "source": "offline fixture, not a Binance response",
        "as_of": "2026-10-09T11:59:00Z",
        "symbols": [binance_symbol("DEMOCOINUSDT"), binance_symbol("BTCUSDT")],
    }
    adapter = SimulatedBinanceSpot(
        equity=Decimal("100000"),
        realized_pnl_today=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        as_of=NOW,
        exchange_info=info,
        quotes={"DEMOCOINUSDT": quote(), "BTCUSDT": quote()},
        specs={
            "DEMOCOINUSDT": cash_spec(volume_step="0.001", volume_min="0.001"),
            "BTCUSDT": cash_spec(volume_step="0.001", volume_min="0.001"),
        },
        sessions_open={"DEMOCOINUSDT": True, "BTCUSDT": True},
    )
    for key, value in overrides.items():
        setattr(adapter, key, value)
    return adapter


def desk(tmp: Path, **kwargs) -> Desk:
    adapters = kwargs.pop(
        "adapters",
        {"alpaca_paper": paper(), "mt5": mt5_adapter(), "binance_spot_testnet": binance()},
    )
    journal = kwargs.pop("journal", None)
    if journal is None:
        from halal_demo.journal import Journal

        journal = Journal(tmp / "journal.jsonl")
    return Desk(
        clock=kwargs.pop("clock", clock()),
        policy=kwargs.pop("policy", test_policy()),
        limits=kwargs.pop("limits", risk_limits()),
        runtime=kwargs.pop("runtime", runtime(True)),
        adapters=adapters,
        journal=journal,
        **kwargs,
    )


FOREX = SYMBOL_CALC_MODE_FOREX
CFD = SYMBOL_CALC_MODE_CFD
NO_LEV = SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE
