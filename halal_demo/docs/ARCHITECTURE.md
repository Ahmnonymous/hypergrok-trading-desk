# How this demo desk is built

HyperGrok splits a trading conversation into roles so the same bot is not researcher, risk officer, and order sender. This fork keeps that split. The roles that use AI may only propose or explain. The checks that can stop a trade are normal Python with no model in the middle.

The original HyperGrok skills and role files are unchanged. Their published counts and file hashes belong to the reviewed v1.5.0 release. New demo roles live in `halal_demo/roles/` so they do not change that pack. Hyperliquid perpetual orders are not a path in this desk.

## Roles

| Piece | Kind | What it may do |
| --- | --- | --- |
| Desk Lead | AI instructions | Route work and keep the proposal id. Cannot approve or send. |
| Market Analyst | AI instructions | Describe prices the adapter already recorded, with source and time. |
| Research Analyst | AI instructions | Explain context. Cannot fill a missing Shariah fact. |
| Strategist | AI instructions | Turn an idea into rules and read an offline backtest. |
| Shariah engine | Python | PASS, REJECT, or REQUIRES_HUMAN_REVIEW. |
| Risk engine | Python | Size, loss, daily stop, position count, stale data. |
| Execution service | Python | One simulated attempt, then reconciliation. |
| Trade Reviewer | AI instructions | Read the journal. Cannot change it into an approval. |

## Path of one idea

```
PROPOSED
  -> INSTRUMENT_VERIFIED
  -> SHARIAH_PASSED
  -> RISK_PASSED
  -> DEMO_ACCOUNT_VERIFIED
  -> ORDER_VALIDATED
  -> ORDER_SUBMITTED
  -> BROKER_STATE_RECONCILED
  -> TRADE_RECORDED
```

`ORDER_SUBMITTED` in this build means the local simulator stored the order. The journal says `network_send` false. A failed or uncertain step stops the chain and writes the reason. Nothing in the chain mints a replacement proposal.

## Shared proposal

Every idea uses the same fields: proposal id, idempotency id, instrument, asset class, venue, the adapter's contract type, direction, entry, stop, optional target, size, estimated loss, data source, data time, strategy, evidence, expiry, then the engine results and the final status. The engines ignore any PASS an agent typed into the proposal.

## Adapters

Each adapter reads a fixture shaped like a real vendor's fields, then returns facts and a destination proof.

- MetaTrader 5 shape for forex and gold. A forex symbol is not treated as deliverable metal or spot just because of its name.
- Gold has its own classifier. `XAUUSD` is never approved from the letters in the name, including on a swap-free account.
- Stocks use a separate paper-trading interface shaped like Alpaca's paper API.
- Crypto uses a Binance Spot testnet shape. Futures, margin, and borrowing are refused.

## What is stored

The journal is an append-only text file. Fields that look like passwords or keys are replaced with `[redacted]` before the write. The journal is the audit trail. Chat is not.
