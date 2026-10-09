# Tests

From the repository root:

```bash
python3 -m unittest discover -s halal_demo/tests -t . -v
bash scripts/check.sh
```

The demo tests use fixtures only. They cover a complete simulated pass, prohibited and unknown Shariah results, missing compliance data, missing and invalid stops, size and daily-loss and position limits, duplicates, expiry, stale prices, a dead adapter, an uncertain send that must be reconciled before another try, a live account, stock and crypto eligibility, price and quantity steps, secret redaction, the kill switch, gold, leveraged forex, and a backtest that cannot enable execution.

The original HyperGrok checks stay in `scripts/check.sh`. They were not switched off.

There is no configured type-checker or linter for this repository. `python3 -m compileall -q halal_demo` compiles the new package. Do not point these tests at a live account to "see if they still pass."
