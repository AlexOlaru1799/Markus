---
name: import-bank-entries-to-saga
description: >-
  Post bank receipts or payments into SAGA Jurnal de Bancă via Markus MCP
  saga_post_bank_entries, from chat rows or an I_/P_ XML. Use when the user
  asks to import încasări / plăți / extrase / associate receipts with invoices.
---

# Bank entries any source → SAGA Jurnal de Bancă

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

Posting is still **Import extrase + Asociere** (not `grid.create` on Solduri),
including Jurnal de bancă valută when `Moneda` / `Valuta` is not RON.
`saga_post_bank_entries` accepts a BankBundle (`entries`) or emits I_/P_ XML
from chat rows and then calls the same workflow as `saga_import_incasari_xml`.

## Checklist

```
- [ ] 1. Detect source: I_*.xml / P_*.xml / chat rows
- [ ] 2. saga_status / saga_login
- [ ] 3. saga_post_bank_entries(document=... or entries=..., confirm_write=false)
- [ ] 4. Show account, line count, asociere default true
- [ ] 5. After explicit user OK → confirm_write=true
```

Optional: `account=` treasury, `partner=` to force one client/supplier on every
row. `kind=bank_receipts` (Încasări) or `bank_payments` (Plăți).

Cash register (chitanță, Registru de casă) is **`saga_add_casa_entry`** /
`add-saga-casa-entry`, not this skill.

Restart Markus MCP if `list_tools` is missing `saga_post_bank_entries`.
