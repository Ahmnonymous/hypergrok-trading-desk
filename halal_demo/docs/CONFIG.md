# Settings

Limits are whatever the JSON file says. If a required field is missing, startup fails. The code does not fill in a risk percent, a spread, or a daily profit of zero.

Agents cannot write these files through a proposal. `refuse_agent_override` keeps the loaded risk object as it was.

## Runtime

`runtime.demo.json` must say:

- `mode` is `demo`
- `allow_network_orders` is false
- `transport` is `local_simulator`

`allow_offline_test_policy` is false in the shipped file. The unit tests turn it on only so a clearly marked fixture can walk the whole path. That fixture is not an adviser signature.

## Risk demo numbers

These numbers are a demo test configuration, not a recommendation:

- 0.25 percent of equity is the most one trade may lose
- 1 percent is the daily loss stop, counting realized and unrealized results
- 3 open positions across every adapter
- one send attempt per approved proposal
- price and account snapshots older than 120 seconds are stale

The file must also name an account currency, an expiry, and correlation groups. A symbol in two groups is an error. A symbol in no group is still limited by the single-trade cap, and a second trade in the same symbol adds to the open-loss sum.

## Shariah file

`shariah.example.json` loads, and its decision status is `unresolved`. Unresolved means the engine will not PASS.

A future file can say `adviser_signed` only after a qualified person fills the reviewer, review date, evidence source, expiry, ownership words they accept, settlement words they accept, business activities, and one record per instrument. Numeric financial ratios, if you paste them into `stock_financial_criteria`, do **not** become a PASS. The engine leaves those for a person. The questions are listed in [ADVISER_DECISIONS.md](ADVISER_DECISIONS.md).

Contract types the program always rejects, even if a file tries to approve them: CFD, futures, perpetual, margin, swap, interest-bearing, lending, option, and leveraged forex. That is a build rule so a chat message cannot soften it.

## Secrets

A config that contains a non-empty password, token, or API key is refused. Use an empty placeholder such as [../.env.example](../.env.example) only as a reminder. This program does not read environment variables for broker access.
