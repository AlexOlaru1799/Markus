---
name: wipe-saga-data
description: >-
  Permanently delete SAGA WEB documents and partners on the connected firm
  (Intrări / Ieșiri with and without valută, then Furnizori and Clienți) via
  Markus MCP saga_wipe_data. Use when the user asks to wipe, clear, empty, or
  delete everything from SAGA (partners, invoices, intrari, iesiri, valuta).
---

# Wipe SAGA firm data

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

This deletes **Intrări valută, Intrări, Ieșiri valută, Ieșiri, Furnizori, Clienți**
on the **currently connected firm**, in that order. It does **not** wipe plan de
conturi, articole, salarii, închidere lună, or company config.

Rows outside the SAGA toolbar interval are not listed and not deleted.

## Checklist

```
- [ ] 1. saga_status / saga_login (pause for email auth / OTP if needed)
- [ ] 2. saga_wipe_data(confirm_write=false) — show firm name, interval, counts
- [ ] 3. After explicit user OK on that firm → saga_wipe_data(confirm_write=true)
- [ ] 4. Report deleted_total, remaining_total, per-grid results
```

## Confirm gate

"Delete everything" does **not** skip `confirm_write=false`. Show:

- `firm_name` / `firm_code`
- toolbar `interval_start` – `interval_end`
- per-grid `count` and sample NrDoc / names

Only call `confirm_write=true` after they confirm **that firm**.

Optional `targets` (comma-separated): `intrari_valuta,intrari,iesiri_valuta,iesiri,furnizori,clienti`.
Default is all of those.

Do not call `saga_reset_session` with `delete_profile=true`.

If `list_tools` is missing `saga_wipe_data`, restart Markus MCP (or bump
`MARKUS_MCP_CATALOG` in `~/.cursor/mcp.json`).
