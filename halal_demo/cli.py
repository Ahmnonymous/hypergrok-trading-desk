"""Command line checks. They do not place orders or open a network connection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from halal_demo import NETWORK_ORDERS_ALLOWED
from halal_demo.config import RuntimeConfig, load_json
from halal_demo.research.loader import load_dataset
from halal_demo.research.ma_crossover import ResearchParams, run_backtest
from halal_demo.risk import RiskLimits
from halal_demo.shariah import ShariahPolicy


ROOT = Path(__file__).resolve().parent


def validate_config(shariah_path: Path, risk_path: Path, runtime_path: Path) -> dict:
    policy = ShariahPolicy.from_dict(load_json(shariah_path))
    limits = RiskLimits.from_dict(load_json(risk_path))
    runtime = RuntimeConfig.from_dict(load_json(runtime_path))
    return {
        "ok": True,
        "network_orders_allowed": NETWORK_ORDERS_ALLOWED,
        "runtime_mode": runtime.mode,
        "allow_network_orders": runtime.allow_network_orders,
        "shariah_rule_version": policy.rule_version,
        "shariah_decision_status": policy.decision_status,
        "risk_rule_version": limits.rule_version,
        "max_risk_per_trade_percent": str(limits.max_risk_per_trade_percent),
        "daily_loss_stop_percent": str(limits.daily_loss_stop_percent),
        "max_open_positions": limits.max_open_positions,
    }


def backtest(csv_path: Path, meta_path: Path, params_path: Path) -> dict:
    dataset = load_dataset(csv_path, meta_path)
    params = ResearchParams.from_dict(load_json(params_path))
    report = run_backtest(dataset, params)
    return {
        "dataset_version": report.dataset_version,
        "dataset_label": report.dataset_label,
        "dataset_source": report.dataset_source,
        "params": report.params,
        "in_sample": _plain(report.in_sample),
        "out_of_sample": _plain(report.out_of_sample),
        "baseline_out_of_sample": _plain(report.baseline_out_of_sample),
        "trade_count": len(report.trades),
        "execution_authorized": report.authorizes_execution(),
    }


def _plain(value):
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if hasattr(value, "as_tuple"):
        return str(value)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline checks for the demo desk")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate-config")
    check.add_argument("--shariah", type=Path, default=ROOT / "config" / "shariah.example.json")
    check.add_argument("--risk", type=Path, default=ROOT / "config" / "risk.demo.json")
    check.add_argument("--runtime", type=Path, default=ROOT / "config" / "runtime.demo.json")
    study = sub.add_parser("backtest")
    study.add_argument("--csv", type=Path, default=ROOT / "fixtures" / "prices_synthetic.csv")
    study.add_argument("--meta", type=Path, default=ROOT / "fixtures" / "prices_synthetic.json")
    study.add_argument("--params", type=Path, default=ROOT / "fixtures" / "ma_params.json")
    args = parser.parse_args(argv)
    if args.command == "validate-config":
        payload = validate_config(args.shariah, args.risk, args.runtime)
    else:
        payload = backtest(args.csv, args.meta, args.params)
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
