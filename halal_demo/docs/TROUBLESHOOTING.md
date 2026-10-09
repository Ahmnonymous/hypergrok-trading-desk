# Troubleshooting

| What you see | What it means |
| --- | --- |
| `REQUIRES_HUMAN_REVIEW` | The checklist does not have a clear pass. A person has to decide. Do not treat the gap as a yes. |
| `structural_reject` | The contract is leveraged, a CFD, a future, a swap, or another blocked structure. A policy file cannot override it. |
| `missing_compliance_data` | A fact the engine needs was blank or unverified. |
| `stale_price` or `unhealthy_services` | The snapshot is old or the adapter is down. The trade stops. |
| `live_account_rejected` | The destination was not proved to be a local demo, paper, or testnet simulator. |
| `duplicate_proposal` | That proposal id was already used, including when the first try was rejected. Choose a new id yourself if the idea really changed. The program will not do that for you. |
| `reconcile_before_retry` or `one_attempt_already_used` | The first send is uncertain or already spent. Read the journal before you assume it failed. |
| `gold_structure_not_identified` | The gold symbol was recognized and still not approved. Swap-free is not enough. |
| Config error on a secret field | Remove the key. Do not commit it. |

## MetaTrader on Windows

The official Python package imports only when the MetaTrader 5 terminal is installed on Windows. This project does not include that step, and the current code refuses the network login even after you install it. A future change would need a separate review before any demo login.

## Practice accounts you might open later

These are manual steps for you. This repository does not do them.

- MetaTrader: install the terminal on Windows and open a broker **demo** account yourself. Do not type the password into this repo.
- Alpaca: their site can open a paper account. Paper is still their server. This code will not call it.
- Binance Spot testnet: Binance can issue testnet keys. This code will not call `testnet.binance.vision`.

If a command tries to print a key, stop and rotate that key at the broker. Do not paste it into chat.
