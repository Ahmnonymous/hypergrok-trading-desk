# Simulation, demo, and live

These words are easy to mix up. This repository uses them as follows.

| Word | Meaning here |
| --- | --- |
| Simulation | The order exists only in memory on this computer. The tests do this. No broker sees it. |
| Demo or paper or testnet account | An account a broker labels as practice. It can still be a remote service. This build does not log in to one. |
| Live | A real-money account. The demo guard rejects it. |

`ORDER_SUBMITTED` in the state list is the simulator's record. The audit line includes `network_send: false` and `destination: local_simulator`.

A backtest is research. Its flag `execution_authorized` is forced false. A profitable report does not create a proposal and does not relax a limit.

Hyperliquid testnet and mainnet, Alpaca live or paper HTTP, Binance testnet or mainnet, and a MetaTrader terminal are all outside this build. Turning `allow_network_orders` to true is a configuration error, not a hidden switch.

The constant `NETWORK_ORDERS_ALLOWED` in `halal_demo/__init__.py` is false. Tests check that it stays false.
