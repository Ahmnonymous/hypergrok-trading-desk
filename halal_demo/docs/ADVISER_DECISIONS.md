# Decisions still needed from a qualified adviser

This software does not issue a fatwa and does not pick a school of law. The questions below are blank on purpose. Until a qualified Shariah adviser answers them in a signed config, the engine stays on REQUIRES_HUMAN_REVIEW for anything that is not already a hard reject (such as a CFD).

Please ask the adviser to write down:

1. Which standard or board applies. The program does not choose AAOIFI or any other body for you.
2. Whether any forex contract is acceptable, and the exact legal structure (deliverable spot, a promise, something else). A MetaTrader symbol name is not that structure.
3. Whether any gold product is acceptable. If yes, which one: allocated metal, unallocated metal, a vault claim, or another named structure. Swap-free `XAUUSD` is not an answer by itself.
4. Which stock business activities are prohibited, and which are allowed. The test file contains a short example list so the software can be tested. The shipped example list is empty. Neither list is a ruling.
5. Which financial ratios, if any, apply to stocks, and what to do when the figures are missing. Do not expect this program to invent a debt, cash, or interest-income percentage.
6. Which crypto assets, if any, are eligible as spot holdings, and why. Futures, margin, and lending are refused by the program regardless.
7. How fees, purification, and custody should be recorded.
8. Who signs the file, the review date, the evidence they relied on, the rule version, and the date the decision expires.
9. How often a name must be screened again.

When those answers exist, a person can edit a **copy** of `config/shariah.example.json`, set `decision_status` to `adviser_signed`, and keep `offline_test_only` false. The program still will not send an order. It will only allow a simulated proposal to reach the later checks.

AI confidence is not one of the fields. Do not add one.
