"""Offline research tests. A backtest cannot authorize an order."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from halal_demo.research.loader import Bar, Dataset, load_dataset
from halal_demo.research.ma_crossover import ResearchParams, run_backtest, signal_at
from halal_demo.tests.support import ROOT


class ResearchTests(unittest.TestCase):
    def test_fixture_backtest_is_labeled_and_cannot_trade(self):
        dataset = load_dataset(ROOT / "fixtures" / "prices_synthetic.csv", ROOT / "fixtures" / "prices_synthetic.json")
        self.assertEqual(dataset.label, "synthetic")
        params = ResearchParams.from_dict(
            {
                "fast": 2,
                "slow": 4,
                "in_sample_fraction": "0.6",
                "spread": "0.05",
                "slippage": "0.05",
                "fee_per_fill": "0.10",
                "size": "1",
            }
        )
        report = run_backtest(dataset, params)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.authorizes_execution())
        self.assertEqual(report.dataset_version, "synthetic-ma-1")
        self.assertIn("trade_count", report.out_of_sample)
        self.assertIn("max_drawdown", report.out_of_sample)
        self.assertIn("win_rate", report.out_of_sample)
        self.assertIn("avg_gain", report.out_of_sample)
        self.assertIn("avg_loss", report.out_of_sample)
        self.assertIn("net", report.out_of_sample)
        self.assertIn("net", report.baseline_out_of_sample)
        self.assertEqual(report.params["fast"], 2)
        forced = type(report)(
            dataset_version=report.dataset_version,
            dataset_label=report.dataset_label,
            dataset_source=report.dataset_source,
            params=report.params,
            in_sample=report.in_sample,
            out_of_sample=report.out_of_sample,
            baseline_out_of_sample=report.baseline_out_of_sample,
            trades=report.trades,
            execution_authorized=True,
        )
        self.assertFalse(forced.execution_authorized)

    def test_signal_does_not_read_a_future_close(self):
        closes = [Decimal(value) for value in ("1", "1", "1", "2", "3", "4")]
        self.assertEqual(signal_at(closes, 3, 2, 3), "up")
        closes[5] = Decimal("100")
        self.assertEqual(signal_at(closes, 3, 2, 3), "up")

    def test_fill_uses_the_next_open(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        closes = [Decimal(v) for v in ("10", "10", "10", "11", "13", "15", "14", "12", "10", "9", "8", "7")]
        bars = []
        previous = closes[0]
        for index, close in enumerate(closes):
            bars.append(
                Bar(
                    start + timedelta(hours=index),
                    previous,
                    max(previous, close),
                    min(previous, close),
                    close,
                )
            )
            previous = close
        dataset = Dataset("tiny", "hand built", "synthetic", start, "DEMO", tuple(bars))
        params = ResearchParams(2, 3, Decimal("0.5"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1"))
        report = run_backtest(dataset, params)
        self.assertGreaterEqual(len(report.trades), 1)
        trade = report.trades[0]
        self.assertEqual(trade.entry_price, bars[trade.entry_index].open)
        self.assertGreater(trade.entry_index, 0)

    def test_live_label_is_refused(self):
        with self.assertRaises(ValueError):
            run_backtest(
                Dataset(
                    "x",
                    "web",
                    "live",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "X",
                    (),
                ),
                ResearchParams(2, 3, Decimal("0.5"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1")),
            )


if __name__ == "__main__":
    unittest.main()
