# Instruments

Nothing here is a list of religiously approved markets. A symbol can be **discussed** only after an adapter identifies the contract. It can **pass** only when the Shariah file also has a matching record and every structural check is clean.

## What the tests use

| Name | What it is |
| --- | --- |
| `DEMOHALAL` | Fake cash stock inside the unit-test policy. Not a company. |
| `DEMOCASH` | Fake MetaTrader symbol in "forex, no account leverage" mode with zero swap. Not a real currency pair. |
| `DEMOCOINUSDT` | Fake spot crypto row. Not a Binance listing. |
| `XAUUSD` | Sent through the gold gate. Not approved. |
| `EURUSD` | Sample leveraged-forex classification. Not approved. |
| `BTCUSDT` | Marked ineligible in the test policy so the crypto check can fail closed. |

## Defaults that stop a symbol

- Unknown contract type: rejected.
- CFD, futures, perpetual, margin, swap, lending, option, leveraged forex: rejected.
- Interest or a swap model: rejected.
- Gold whose delivery structure is not identified: human review, never an automatic pass.
- Stock with no verified business activity, or with an activity on the configured prohibited list: not a pass.
- Stock financial ratios present as numbers: human review. This program does not apply a debt or cash percentage.
- Crypto that is not on the eligibility list, or is marked ineligible: not a pass.
- Missing, unverified, or stale data: not a pass.
- A live or contest account: rejected by the demo guard.

The shipped checklist has an empty approval list. See [ADVISER_DECISIONS.md](ADVISER_DECISIONS.md).
