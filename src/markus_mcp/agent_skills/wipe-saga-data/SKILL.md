---
name: wipe-saga-data
description: >-
  Permanently delete SAGA WEB documents, bank journal, and partners on the
  connected firm (Jurnal de bancă including Import extrase staging, Intrări /
  Ieșiri with and without valută including lines and receipt allocations, then
  Furnizori and Clienți) via Markus MCP saga_wipe_data. Use when the user
  asks to wipe, clear, empty, or delete everything from SAGA (partners,
  invoices, intrari, iesiri, valuta, jurnal de banca).
---

# Wipe SAGA firm data

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

This deletes **Jurnal de bancă, Intrări valută, Intrări, Ieșiri valută, Ieșiri,
Furnizori, Clienți** on the **currently connected firm**, in that order. It does
**not** wipe plan de conturi, articole, salarii, închidere lună, or company
config.

Jurnal de bancă (`https://web2.sagasoft.ro/sagac/JurnalDeBanca`) is wiped
**first** so associated receipts do not block invoice delete. It clears
**Import extrase** staging (`RegistruCasa/ClearCacheImport`), then each day's
**intrări din zi**, then the day header. Deleting the day while entries remain
returns `ATENTIE! Stergeti intai intrarile din zi.`

Ieșiri / Ieșiri valută delete **Iesiri_Incasari** allocations and detail lines
before the invoice header. Intrări / Intrări valută delete detail lines first.

Rows outside the SAGA toolbar interval are not listed and not deleted.

Do **not** call this tool until the user explicitly asks to wipe, and still
preview first.

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
- per-grid `count` and sample NrDoc / names (for Jurnal de bancă also `days_count` / `entry_count`)

Only call `confirm_write=true` after they confirm **that firm**.

Optional `targets` (comma-separated): `jurnal_banca,intrari_valuta,intrari,iesiri_valuta,iesiri,furnizori,clienti`.
Default is all of those.

Do not call `saga_reset_session` with `delete_profile=true`.

If `list_tools` is missing `saga_wipe_data`, restart Markus MCP (or bump
`MARKUS_MCP_CATALOG` in `~/.cursor/mcp.json`).
