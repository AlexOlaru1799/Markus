---
name: import-iesiri-xml-to-saga
description: >-
  Create RON Ieșiri (sales invoices) from a SAGA Facturi XML via Markus MCP
  saga_import_iesiri_xml. Use when the user provides an F_*.xml path with
  ClientNume/ClientCod and asks to import Ieșiri / sales invoices / iesiri
  into SAGA (not Import date, not IesiriValuta, not I_/P_ bank XML).
---

# Import Ieșiri XML into SAGA

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

This is **not** `saga_import_xml` / Import date (purchases / Intrări valută).
This is **not** `saga_add_iesiri_valuta` (FX). This is **not**
`saga_import_incasari_xml` (I_/P_ bank receipts).

`saga_import_iesiri_xml` opens **Ieșiri**, posts `Iesiri/Create_Iesiri` plus
line creates, and keeps **NrDoc** = `<FacturaNumar>` so Jurnal de Bancă
Asociere can match receipts. Existing NrDoc values are **skipped**.

Typical file: `F_<cif>_<dd>_<mm>_<yyyy>.xml` with root `<Facturi>`,
`<ClientNume>` / `<ClientCod>`, line `<Cont>` (default 704) and `<TVAProc>`.

Demo export of the 25 DEMO D* invoices:

- `~/.markus/data/saga/F_42375308_13_08_2026.xml`
- `~/Downloads/F_42375308_13_08_2026.xml`

Those invoices are already on the firm. A second import should report them as
skipped, not create duplicates.

## Checklist

```
- [ ] 1. saga_status / saga_login (pause for email auth / OTP if needed)
- [ ] 2. saga_import_iesiri_xml(xml_path, confirm_write=false) — show preview
- [ ] 3. After explicit user OK → saga_import_iesiri_xml(..., confirm_write=true)
- [ ] 4. Report created_count, skipped_count, failed_count, screenshot_path
```

## Path

`xml_path` is the file the user named. Do not rename it unless they ask.
Warn if it is `I_*.xml` / `P_*.xml` — those belong on Jurnal de Bancă.
Warn if it looks like purchases (many FurnizorNume, one ClientNume) — use
`saga_import_xml`.

Clients must already exist (or have matching Cod on Clienți). This tool does
not create partners.

## Confirm gate

The user's "import this XML" does **not** skip `confirm_write=false`. Show
invoice_count, filename, totals, warnings. Only call `confirm_write=true`
after they say yes.

Do not call `saga_reset_session` with `delete_profile=true`.

Reload the Markus MCP server after code changes before calling the new tool.
If `list_tools` is missing `saga_import_iesiri_xml`, restart Markus MCP.
