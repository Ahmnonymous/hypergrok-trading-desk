"""Gate tests. Every broker in here is a local simulator."""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from halal_demo import NETWORK_ORDERS_ALLOWED
from halal_demo.adapters.book import PreparedOrder
from halal_demo.adapters.mt5 import GuardedMT5Terminal, open_network_terminal
from halal_demo.adapters.mt5_constants import ACCOUNT_TRADE_MODE_REAL
from halal_demo.config import ConfigError, RuntimeConfig, load_json
from halal_demo.demo_guard import DestinationProof, verify_destination
from halal_demo.errors import DemoOnlyError
from halal_demo.journal import Journal
from halal_demo.pipeline import activate_kill_switch, run_proposal
from halal_demo.shariah import ShariahPolicy
from halal_demo.tests.support import (
    CFD,
    FOREX,
    NOW,
    QUOTE,
    ROOT,
    binance,
    cash_spec,
    desk,
    mt5_adapter,
    mt5_symbol,
    mt5_terminal,
    paper,
    proposal,
    quote,
    risk_limits,
    runtime,
    stock_asset,
    test_policy,
)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def test_valid_proposal_passes_simulated_pipeline(self):
        board = desk(self.path)
        result = run_proposal(proposal(), board)
        self.assertEqual(result.final_status, "TRADE_RECORDED", result.block_reason)
        self.assertEqual(
            result.stage_names(),
            [
                "PROPOSED",
                "INSTRUMENT_VERIFIED",
                "SHARIAH_PASSED",
                "RISK_PASSED",
                "DEMO_ACCOUNT_VERIFIED",
                "ORDER_VALIDATED",
                "ORDER_SUBMITTED",
                "BROKER_STATE_RECONCILED",
                "TRADE_RECORDED",
            ],
        )
        self.assertFalse(result.network_send)
        self.assertEqual(result.order_count, 1)
        text = (self.path / "journal.jsonl").read_text(encoding="utf-8")
        self.assertIn("TRADE_RECORDED", text)
        self.assertIn("offline-test-2026-10-09", text)
        self.assertIn("demo-risk-2026-10-09", text)
        self.assertNotIn("api_key", text.lower())

    def test_prohibited_instrument_and_business_are_rejected(self):
        board = desk(self.path)
        stock = board.adapters["alpaca_paper"]
        stock.assets["BANCO"] = stock_asset("BANCO", business_activity="conventional_banking")
        stock.quotes["BANCO"] = quote()
        stock.specs["BANCO"] = cash_spec()
        stock.sessions_open["BANCO"] = True
        result = run_proposal(
            proposal(proposal_id="HD-20261009-02", idempotency_id="hd-20261009-02", instrument="BANCO"),
            board,
        )
        self.assertEqual(result.final_status, "BLOCKED")
        self.assertIn("prohibited_instrument", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_unknown_shariah_status_requires_human_review(self):
        board = desk(self.path)
        stock = board.adapters["alpaca_paper"]
        stock.assets["OTHERCO"] = stock_asset("OTHERCO")
        stock.quotes["OTHERCO"] = quote()
        stock.specs["OTHERCO"] = cash_spec()
        stock.sessions_open["OTHERCO"] = True
        result = run_proposal(
            proposal(proposal_id="HD-20261009-03", idempotency_id="hd-20261009-03", instrument="OTHERCO"),
            board,
        )
        self.assertIn("REQUIRES_HUMAN_REVIEW", result.block_reason)
        self.assertNotIn("shariah:PASS", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_missing_compliance_data_never_passes(self):
        board = desk(self.path)
        stock = board.adapters["alpaca_paper"]
        stock.assets["DEMOHALAL"] = stock_asset(data_verified=False, financials_verified=False)
        result = run_proposal(proposal(shariah_result="PASS", risk_result="PASS"), board)
        self.assertIn("REQUIRES_HUMAN_REVIEW", result.block_reason)
        self.assertIn("missing_compliance_data", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_shipped_policy_cannot_pass_a_clean_stock(self):
        policy = ShariahPolicy.from_dict(load_json(ROOT / "config" / "shariah.example.json"))
        board = desk(self.path, policy=policy, runtime=runtime(False))
        result = run_proposal(proposal(shariah_result="PASS"), board)
        self.assertNotEqual(result.final_status, "TRADE_RECORDED")
        self.assertNotIn("shariah:PASS", result.block_reason or "")
        self.assertEqual(result.order_count, 0)

    def test_missing_and_invalid_stop_are_rejected(self):
        board = desk(self.path)
        missing = run_proposal(proposal(stop_loss=None), board)
        self.assertIn("missing_stop_loss", missing.block_reason)
        invalid = run_proposal(
            proposal(proposal_id="HD-20261009-04", idempotency_id="hd-20261009-04", stop_loss="101"),
            board,
        )
        self.assertIn("invalid_stop_loss", invalid.block_reason)
        self.assertEqual(board.adapters["alpaca_paper"].book.orders, {})

    def test_excessive_size_is_rejected(self):
        board = desk(self.path)
        result = run_proposal(proposal(size="400", max_estimated_loss="1000"), board)
        self.assertIn("excessive_risk", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_daily_loss_stop_blocks(self):
        board = desk(self.path)
        board.adapters["alpaca_paper"].realized_pnl_today = Decimal("-1000")
        result = run_proposal(proposal(), board)
        self.assertIn("daily_loss_stop", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_position_limit_is_shared_across_adapters(self):
        board = desk(self.path)
        specs = [
            proposal(),
            proposal(
                proposal_id="HD-20261009-11",
                idempotency_id="hd-20261009-11",
                instrument="DEMOCASH",
                asset_class="forex",
                venue="mt5",
                contract_type="forex_no_account_leverage",
            ),
            proposal(
                proposal_id="HD-20261009-12",
                idempotency_id="hd-20261009-12",
                instrument="DEMOCOINUSDT",
                asset_class="crypto",
                venue="binance_spot_testnet",
                contract_type="spot",
            ),
        ]
        for body in specs:
            result = run_proposal(body, board)
            self.assertEqual(result.final_status, "TRADE_RECORDED", (body["venue"], result.block_reason))
        self.assertEqual(len(board.book), 3)
        fourth = run_proposal(
            proposal(proposal_id="HD-20261009-13", idempotency_id="hd-20261009-13"),
            board,
        )
        self.assertIn("position_limit", fourth.block_reason)
        self.assertEqual(len(board.book), 3)

    def test_duplicate_cannot_create_a_second_order(self):
        board = desk(self.path)
        first = run_proposal(proposal(), board)
        second = run_proposal(proposal(size="11"), board)
        self.assertEqual(first.final_status, "TRADE_RECORDED")
        self.assertEqual(second.block_reason, "duplicate_proposal")
        self.assertEqual(len(board.adapters["alpaca_paper"].book.orders), 1)

    def test_expired_and_malformed_are_rejected_and_not_rewritten(self):
        board = desk(self.path)
        expired = run_proposal(proposal(expiry="2026-10-09T11:00:00Z"), board)
        self.assertIn("expired", expired.block_reason)
        again = run_proposal(proposal(), board)
        self.assertEqual(again.block_reason, "duplicate_proposal")
        malformed = run_proposal(
            proposal(proposal_id="HD-20261009-20", idempotency_id="hd-20261009-20", direction="long"),
            board,
        )
        self.assertIn("malformed:direction", malformed.block_reason)
        incomplete = run_proposal(
            proposal(proposal_id="HD-20261009-21", idempotency_id="hd-20261009-21", evidence=""),
            board,
        )
        self.assertIn("incomplete:evidence", incomplete.block_reason)
        self.assertEqual(board.adapters["alpaca_paper"].book.orders, {})

    def test_stale_price_and_unavailable_api_block(self):
        board = desk(self.path)
        stock = board.adapters["alpaca_paper"]
        stock.quotes["DEMOHALAL"] = quote(when=NOW.replace(hour=10))
        stale = run_proposal(proposal(data_timestamp="2026-10-09T10:00:00Z"), board)
        self.assertIn("stale_price", stale.block_reason)
        stock.quotes["DEMOHALAL"] = quote()
        stock.assets.pop("DEMOHALAL")
        down = run_proposal(
            proposal(proposal_id="HD-20261009-22", idempotency_id="hd-20261009-22"),
            board,
        )
        self.assertIn("api_unavailable", down.block_reason)
        self.assertEqual(stock.book.orders, {})

    def test_uncertain_submission_is_reconciled_before_any_retry(self):
        board = desk(self.path)
        board.adapters["alpaca_paper"].book.mode = "uncertain"
        result = run_proposal(proposal(), board)
        self.assertEqual(result.block_reason, "uncertain_submission")
        self.assertEqual(len(board.adapters["alpaca_paper"].book.orders), 1)
        prepared = PreparedOrder(
            "HD-20261009-01",
            "hd-20261009-01",
            "alpaca_paper",
            "DEMOHALAL",
            "buy",
            "limit",
            Decimal("100"),
            Decimal("99"),
            Decimal("105"),
            Decimal("10"),
            "synthetic",
            False,
        )
        early = board.execution().submit(board.adapters["alpaca_paper"], prepared)
        self.assertEqual(early.reason, "reconcile_before_retry")
        matched, status = board.execution().reconcile(board.adapters["alpaca_paper"], prepared)
        self.assertTrue(matched, status)
        late = board.execution().submit(board.adapters["alpaca_paper"], prepared)
        self.assertEqual(late.reason, "one_attempt_already_used")
        self.assertEqual(len(board.adapters["alpaca_paper"].book.orders), 1)
        fresh_journal = Journal(self.path / "journal.jsonl")
        from halal_demo.execution import ExecutionService
        from halal_demo.killswitch import KillSwitch

        restarted = ExecutionService(fresh_journal, KillSwitch())
        fresh_adapter = paper()
        outcome = restarted.submit(fresh_adapter, prepared)
        self.assertEqual(outcome.reason, "one_attempt_already_used")
        self.assertEqual(fresh_adapter.book.orders, {})

    def test_live_account_is_rejected_by_the_demo_guard(self):
        board = desk(self.path)
        board.adapters["alpaca_paper"].account_type = "live"
        result = run_proposal(proposal(), board)
        self.assertIn("live_account_rejected", result.block_reason)
        self.assertEqual(result.order_count, 0)
        proof = DestinationProof("mt5", "live", "network", True, "broker.example", "adapter_configuration", "real", "no")
        self.assertFalse(verify_destination(proof).passed)
        with self.assertRaises(ConfigError):
            RuntimeConfig.from_dict(
                {"mode": "live", "allow_network_orders": True, "transport": "network", "allow_offline_test_policy": False}
            )

    def test_stock_and_crypto_eligibility_failures(self):
        board = desk(self.path)
        stock = board.adapters["alpaca_paper"]
        stock.assets["BANK"] = stock_asset("BANK", business_activity="conventional_banking")
        stock.quotes["BANK"] = quote()
        stock.specs["BANK"] = cash_spec()
        stock.sessions_open["BANK"] = True
        stock_result = run_proposal(
            proposal(proposal_id="HD-20261009-30", idempotency_id="hd-20261009-30", instrument="BANK"),
            board,
        )
        self.assertIn("prohibited_business_activity", stock_result.block_reason)
        crypto = run_proposal(
            proposal(
                proposal_id="HD-20261009-31",
                idempotency_id="hd-20261009-31",
                instrument="BTCUSDT",
                asset_class="crypto",
                venue="binance_spot_testnet",
                contract_type="spot",
            ),
            board,
        )
        self.assertIn("crypto_not_eligible", crypto.block_reason)
        self.assertEqual(stock.book.orders, {})
        self.assertEqual(board.adapters["binance_spot_testnet"].book.orders, {})

    def test_precision_and_min_notional_are_enforced(self):
        board = desk(self.path)
        fuzzy = run_proposal(proposal(entry="100.001", max_estimated_loss="250"), board)
        self.assertIn("stock_price_precision", fuzzy.block_reason)
        crypto = run_proposal(
            proposal(
                proposal_id="HD-20261009-32",
                idempotency_id="hd-20261009-32",
                instrument="DEMOCOINUSDT",
                asset_class="crypto",
                venue="binance_spot_testnet",
                contract_type="spot",
                entry="100.00",
                size="0.050",
                max_estimated_loss="250",
            ),
            board,
        )
        self.assertIn("min_notional", crypto.block_reason)
        self.assertEqual(board.adapters["binance_spot_testnet"].book.orders, {})

    def test_audit_log_redacts_secrets(self):
        journal = Journal(self.path / "audit.jsonl")
        journal.append(
            {
                "event": "note",
                "api_key": "super-secret-value",
                "detail": "AKIAIOSFODNN7EXAMPLE",
                "proposal_id": "HD-20261009-40",
            }
        )
        text = (self.path / "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("super-secret-value", text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", text)
        self.assertIn("HD-20261009-40", text)
        self.assertIn("[redacted]", text)

    def test_kill_switch_blocks_and_applies_order_policy(self):
        board = desk(self.path)
        with self.assertRaises(PermissionError):
            activate_kill_switch(
                board,
                actor="agent",
                order_policy="hold",
                position_policy="hold",
                reason="agent must not throw this switch",
            )
        activate_kill_switch(
            board,
            actor="user",
            order_policy="hold",
            position_policy="hold",
            reason="stop new demo orders",
        )
        blocked = run_proposal(proposal(), board)
        self.assertIn("kill_switch", blocked.block_reason)
        self.assertEqual(board.adapters["alpaca_paper"].book.orders, {})
        from halal_demo.adapters.book import BrokerOrder

        resting = board.adapters["alpaca_paper"].book
        resting.orders["open-1"] = BrokerOrder(
            "open-1", "HD-open", "DEMOHALAL", "buy", Decimal("100"), Decimal("1"), Decimal("99"), "open", "alpaca_paper"
        )
        activate_kill_switch(
            board,
            actor="operator",
            order_policy="cancel_unfilled_in_simulator",
            position_policy="hold",
            reason="cancel resting simulator orders and hold positions",
        )
        self.assertEqual(resting.orders["open-1"].status, "cancelled")

    def test_gold_is_not_auto_approved_and_cfd_is_rejected(self):
        cfd = mt5_adapter(
            symbols={
                "XAUUSD": mt5_symbol("XAUUSD", CFD, path="Metals\\CFD"),
            }
        )
        board = desk(self.path, adapters={"mt5": cfd, "alpaca_paper": paper(), "binance_spot_testnet": binance()})
        cfd_result = run_proposal(
            proposal(
                proposal_id="HD-20261009-50",
                idempotency_id="hd-20261009-50",
                instrument="XAUUSD",
                asset_class="gold",
                venue="mt5",
                contract_type="cfd",
            ),
            board,
        )
        self.assertIn("structural_reject:cfd", cfd_result.block_reason)
        swap_free = mt5_adapter(
            symbols={"XAUUSD": mt5_symbol("XAUUSD", 5, path="Metals\\Islamic")},
        )
        board.adapters["mt5"] = swap_free
        review = run_proposal(
            proposal(
                proposal_id="HD-20261009-51",
                idempotency_id="hd-20261009-51",
                instrument="XAUUSD",
                asset_class="gold",
                venue="mt5",
                contract_type="unidentified_gold_otc",
            ),
            board,
        )
        self.assertIn("REQUIRES_HUMAN_REVIEW", review.block_reason)
        self.assertIn("gold_structure_not_identified", review.block_reason)
        self.assertEqual(swap_free.terminal.book.orders, {})

    def test_forex_symbol_is_not_treated_as_deliverable_spot(self):
        adapter = mt5_adapter(symbols={"EURUSD": mt5_symbol("EURUSD", FOREX, path="Forex")})
        board = desk(self.path, adapters={"mt5": adapter, "alpaca_paper": paper(), "binance_spot_testnet": binance()})
        result = run_proposal(
            proposal(
                proposal_id="HD-20261009-52",
                idempotency_id="hd-20261009-52",
                instrument="EURUSD",
                asset_class="forex",
                venue="mt5",
                contract_type="leveraged_forex",
            ),
            board,
        )
        self.assertIn("structural_reject:leveraged", result.block_reason)
        self.assertEqual(adapter.terminal.book.orders, {})

    def test_correlated_exposure_is_summed(self):
        limits = risk_limits(max_open_risk_percent="0.30")
        board = desk(self.path, limits=limits)
        first = run_proposal(proposal(size="200", max_estimated_loss="250"), board)
        self.assertEqual(first.final_status, "TRADE_RECORDED", first.block_reason)
        second = run_proposal(
            proposal(
                proposal_id="HD-20261009-60",
                idempotency_id="hd-20261009-60",
                size="200",
                max_estimated_loss="250",
            ),
            board,
        )
        self.assertIn("correlated_exposure_limit", second.block_reason)

    def test_network_entry_points_refuse_and_do_not_import_metatrader(self):
        self.assertFalse(NETWORK_ORDERS_ALLOWED)
        with self.assertRaises(DemoOnlyError):
            open_network_terminal()
        import sys

        self.assertNotIn("MetaTrader5", sys.modules)
        fake = type("Fake", (), {"is_local_simulator": False, "sent": False})()

        def order_send(_request):
            fake.sent = True

        fake.order_send = order_send
        with self.assertRaises(DemoOnlyError):
            GuardedMT5Terminal(fake).order_send({})
        self.assertFalse(fake.sent)
        crypto = binance()
        with self.assertRaises(RuntimeError):
            crypto.futures_create_order()
        with self.assertRaises(RuntimeError):
            crypto.margin_borrow()

    def test_real_market_label_is_blocked(self):
        board = desk(self.path)
        board.adapters["alpaca_paper"].quotes["DEMOHALAL"] = quote(label="real_market_data")
        result = run_proposal(proposal(), board)
        self.assertIn("market_data_label_rejected", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_missing_daily_pnl_blocks(self):
        board = desk(self.path)
        board.adapters["alpaca_paper"].realized_pnl_today = None
        result = run_proposal(proposal(), board)
        self.assertIn("missing:realized_pnl_today", result.block_reason)

    def test_unhealthy_service_blocks(self):
        from halal_demo.health import ComponentHealth

        board = desk(self.path, health_overrides={"alpaca_paper": ComponentHealth("alpaca_paper", False, "down")})
        result = run_proposal(proposal(), board)
        self.assertIn("unhealthy_services", result.block_reason)
        self.assertEqual(result.order_count, 0)

    def test_live_mt5_trade_mode_constant_is_not_demo(self):
        self.assertEqual(ACCOUNT_TRADE_MODE_REAL, 2)
        adapter = mt5_adapter(trade_mode=ACCOUNT_TRADE_MODE_REAL)
        proof = adapter.destination_proof()
        decision = verify_destination(proof)
        self.assertFalse(decision.passed)
        self.assertTrue(any("live" in reason or "real" in reason for reason in decision.reasons))

    def _open_order(self):
        return PreparedOrder(
            "HD-open",
            "open-1",
            "alpaca_paper",
            "DEMOHALAL",
            "buy",
            "limit",
            Decimal("100"),
            Decimal("99"),
            None,
            Decimal("1"),
            "synthetic",
            False,
        )


class DirectGateTests(unittest.TestCase):
    def test_gold_deliverable_label_still_needs_an_explicit_record(self):
        from halal_demo.shariah import evaluate as shariah_evaluate

        facts = _gold_facts()
        decision = shariah_evaluate(facts, test_policy(), NOW, allow_offline_test_policy=True)
        self.assertEqual(decision.status, "REQUIRES_HUMAN_REVIEW")

    def test_agent_cannot_change_risk_limits(self):
        from halal_demo.risk import refuse_agent_override

        limits = risk_limits()
        same, note = refuse_agent_override(limits, {"max_risk_per_trade_percent": "50"})
        self.assertIs(same, limits)
        self.assertEqual(note, "agent_override_ignored")
        self.assertEqual(same.max_risk_per_trade_percent, Decimal("0.25"))


def _gold_facts():
    from halal_demo.shariah import InstrumentFacts

    return InstrumentFacts(
        instrument="XAUUSD",
        asset_class="gold",
        venue="mt5",
        contract_type="identified_deliverable_spot",
        leverage_class="none",
        swap_state="disabled",
        interest_bearing="no",
        ownership="fixture_cash_securities",
        settlement="fixture_t_plus_demo",
        business_activity=None,
        business_activity_verified=False,
        financials_verified=False,
        data_verified=True,
        market_data_label="synthetic",
        gold_symbol=True,
        contract_structure_identified=True,
        source="hand_built_for_the_engine_test",
        quoted_at=QUOTE,
    )


class ConfigTests(unittest.TestCase):
    def test_shipped_runtime_and_risk_load_and_reject_secrets(self):
        runtime_config = RuntimeConfig.from_dict(load_json(ROOT / "config" / "runtime.demo.json"))
        self.assertFalse(runtime_config.allow_network_orders)
        self.assertFalse(runtime_config.allow_offline_test_policy)
        limits = risk_limits()
        self.assertEqual(limits.max_open_positions, 3)
        with self.assertRaises(ConfigError):
            load_json_payload = {"api_key": "nope"}
            from halal_demo.config import _reject_secrets

            _reject_secrets(load_json_payload)


if __name__ == "__main__":
    unittest.main()
