# Accountant scenarios

Sanitized notes from accountant testing. No real names, CIFs, passwords, or production files.

For a browser-only defect: add a short `.md` here describing expected vs actual, then the narrowest unit test under `tests/`.

# Findings

| Date | Flow | Class | Expected | Actual | Test | Status |
|---|---|---|---|---|---|---|
| 2026-08-19 | Plan de conturi: add DEMO 60013 as synthetic | missing feature | New Plan de conturi row; SAGA rejects 60013 / 6013.A; valid analytic on 601 is 601.3A Tip=A | Classic RowData + Tip A/P/B required; GetTipSintetic | `test_chart_of_accounts_create_preview` | done |
