# Providers

No provider in this build is connected. The adapters copy the public shape of three real products so later work has a place to put a read-only client. They do not open that client.

## MetaTrader 5

The official `MetaTrader5` Python package is documented by MetaQuotes: account info, symbol info, ticks, sessions, `order_check`, and `order_send`. The simulator in `halal_demo/adapters/mt5.py` uses those names.

This program never calls `MetaTrader5.initialize`. `order_send` on anything that is not the local simulator raises an error before a send.

A symbol's calculation mode decides the contract. Forex mode uses account leverage in MetaTrader's own formula, so it is treated as leveraged, not as deliverable spot. Swap-free (sometimes called an Islamic account) only says the swap fields are zero. It does not identify the legal contract.

The package itself runs on Windows beside the terminal. Linux can run these tests because they never load the package.

## Gold

Gold symbols (`XAUUSD` and paths that contain "metal") use `halal_demo/adapters/gold.py`. CFD and futures modes are rejected. Any other MetaTrader mode stays `unidentified_gold_otc` and needs a person. The classifier never emits "deliverable spot" from MetaTrader fields, because those fields do not prove allocated metal in a vault.

## Stocks: Alpaca paper

Alpaca publishes a paper-trading API that is separate from its live API.

- Paper host: `https://paper-api.alpaca.markets`
- Live host: `https://api.alpaca.markets`
- Description: [Alpaca paper trading](https://docs.alpaca.markets/docs/paper-trading)

Paper trading there is a real Alpaca feature: simulated fills, and their market data is their market data, not ours. **This repository does not call either host.** Our quotes are labeled `synthetic` or `offline_fixture`. A label of real market data is blocked, because this build did not fetch it.

If an asset is marginable, or the paper account multiplier is not 1, this adapter will not call it a cash equity.

## Binance Spot testnet

Binance publishes a spot testnet at `https://testnet.binance.vision`. That is not the live exchange and it is not the futures testnet. This adapter keeps spot filters only: tick size, lot step, and minimum notional. It refuses futures and margin methods.

Testnet prices are the testnet's prices. They are not a promise about the live market. This build does not download them. Fixtures must say `synthetic` or `offline_fixture`.

## Hyperliquid

The original desk's Hyperliquid skills remain for that product's own research instructions. This demo path rejects a Hyperliquid venue. Perpetual futures are outside the spot-only rules of this project.
