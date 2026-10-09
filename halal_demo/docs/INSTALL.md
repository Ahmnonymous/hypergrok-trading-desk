# Install

You need Python 3.11 or newer. This package uses the Python standard library only. There is no `pip install` step and no broker SDK.

From the repository root:

```bash
python3 -m compileall -q halal_demo
python3 -m unittest discover -s halal_demo/tests -t .
python3 -m halal_demo validate-config
python3 -m halal_demo backtest
```

`validate-config` reads the example settings and prints their versions. It does not trade.

`backtest` reads the synthetic price file and prints a research report. The report cannot authorize an order.

The full repository check, including the original HyperGrok checks, is:

```bash
bash scripts/check.sh
```

## Settings files

| File | Purpose |
| --- | --- |
| `halal_demo/config/shariah.example.json` | Unfinished checklist. Nothing is approved. |
| `halal_demo/config/risk.demo.json` | Demo loss and position limits. |
| `halal_demo/config/runtime.demo.json` | Forces the local simulator. |
| `halal_demo/.env.example` | Empty placeholders. The code does not read them. |

Copy a config only if you are editing a local copy for study. Do not put real keys in it. See [CONFIG.md](CONFIG.md).

## What this computer does not do

The MetaTrader 5 Python package runs on Windows, next to a MetaTrader terminal. This project does not import that package. Binance and Alpaca accounts are not contacted. See [BOUNDARIES.md](BOUNDARIES.md) and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
