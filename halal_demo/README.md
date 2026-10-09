# Demo research desk

This folder is a **practice-only** research desk. It reuses the HyperGrok idea of separate roles, then puts the safety decisions in ordinary Python instead of in a chat prompt.

It does not send orders. It does not log in to MetaTrader, Binance, Alpaca, or Hyperliquid. A passing test only means the simulator on this computer accepted a made-up example.

The original HyperGrok instruction pack (seventeen skills and seven roles, reviewed release v1.5.0) is still in the repository. This desk does not use Hyperliquid perpetual futures, and it does not use the Hyperliquid order path.

Based on [HyperGrok Trading Desk](https://github.com/galleonlabs/hypergrok-trading-desk) by [Andrew Wilkinson](https://andrewwilkinson.io) and [Galleon Labs](https://github.com/galleonlabs). Used under the MIT license. See [NOTICE.md](NOTICE.md).

## What you can ask it to do

People and AI roles may **suggest** a trade and explain the evidence. They cannot approve it.

The computer then walks a fixed path:

1. Is the proposal complete, unique, and still in date?
2. Did a market adapter actually identify the contract?
3. Did the Shariah checklist say PASS?
4. Did the risk checklist say pass?
5. Is the destination a local demo simulator, not a live account?
6. Does the prepared order match the venue's price and size steps?
7. Record one simulated attempt, read it back, and write the journal.

Any missing fact, unknown religious status, stale price, or unhealthy check stops the path. The software does not invent a new proposal to replace a rejected one.

## Read next

| Topic | File |
| --- | --- |
| How the pieces fit | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Install and commands | [docs/INSTALL.md](docs/INSTALL.md) |
| Settings | [docs/CONFIG.md](docs/CONFIG.md) |
| Brokers and what they cannot prove | [docs/PROVIDERS.md](docs/PROVIDERS.md) |
| Which symbols are supported | [docs/INSTRUMENTS.md](docs/INSTRUMENTS.md) |
| Simulation, demo, and live | [docs/BOUNDARIES.md](docs/BOUNDARIES.md) |
| Tests | [docs/TESTING.md](docs/TESTING.md) |
| When something fails | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Decisions a Shariah adviser still has to make | [docs/ADVISER_DECISIONS.md](docs/ADVISER_DECISIONS.md) |

## Honest limits

No instrument in the shipped settings is religiously approved. The file `config/shariah.example.json` is unfinished on purpose. The names used in tests, such as `DEMOHALAL`, are fake.

A good backtest does not turn on trading. The research report has `execution_authorized` fixed to false.
