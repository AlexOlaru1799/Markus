---
name: add-saga-casa-entry
description: >-
  Add a Registru de casă (cash register) entry via Markus MCP saga_add_casa_entry.
  Use when the user asks for a chitanță, casă, cash receipt, or Registru de casă
  row (not Jurnal de Bancă / I_/P_ XML).
---

# Cash register entry → SAGA Registru de casă

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

This is **not** Jurnal de Bancă. Bank receipts/payments use
`saga_post_bank_entries` / `import-bank-entries-to-saga`.

## Checklist

```
- [ ] 1. saga_status / saga_login
- [ ] 2. saga_add_casa_entry(fields, confirm_write=false)
- [ ] 3. After explicit user OK → confirm_write=true
```

Required fields: **Data**, **Suma**, **Cont** (e.g. 5311). Optional: NrDoc /
chitanță number, Explicatie, FacturaNumar. Pass only user-specified fields.

If **Valuta / Moneda is not RON**, the same tool posts on Registru de casă valută
and fills **Curs** from GetLastValuta when omitted.

Restart Markus MCP if `list_tools` is missing `saga_add_casa_entry`.
