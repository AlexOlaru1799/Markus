---
name: import-sales-invoice-to-saga
description: >-
  Put a RON sales invoice into SAGA WEB Ieșiri via Markus MCP saga_add_iesire,
  from chat fields, a readable PDF, or a Facturi XML (F_*.xml). Use when the
  user asks to add/create/import an Ieșire / sales invoice / factură clienți
  (not FX IesiriValuta, not Import date purchases, not I_/P_ bank XML).
---

# Sales invoice any source → SAGA Ieșiri

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

One posting path: **`saga_add_iesire(header, lines)`**. XML is ingest, not the
tool contract. `saga_import_iesiri_xml` is a convenience wrapper around the
same `post_on_page` path (skips existing NrDoc).

If `Valuta` / currency is not RON, call **`saga_add_iesiri_valuta`** instead
(or pass the FX fields to `saga_add_iesire`, which routes).

## Checklist

```
- [ ] 1. Detect source: chat fields / PDF path / F_*.xml
- [ ] 2. saga_describe_screen("iesiri") if unsure of columns
- [ ] 3. saga_status / saga_login (pause for email auth / OTP)
- [ ] 4. Ensure client exists (saga_search_partners / saga_create_partner).
      The adapter resolves Clienți on confirm and **aborts if missing** (no auto-create).
- [ ] 5. Map to header + lines (Client or Cod, Data, lines with Cont)
- [ ] 6. saga_add_iesire(..., confirm_write=false) — show mapped preview
- [ ] 7. After explicit user OK → confirm_write=true
- [ ] 8. Report NrDoc, id, line_count
```

## Sources

- **Chat:** user-specified fields only. Never invent Cont, TVA, or amounts.
- **PDF:** extract the same fields; text-readable PDFs only.
- **XML:** `saga_parse_facturi_xml` then `saga_add_iesire(document=...)`, or
  `saga_import_iesiri_xml` for a multi-invoice file (existing NrDoc skipped).

Each line needs **Cont** (e.g. 704 / 707). Default 704 only when the XML omitted
`<Cont>` on a sales Facturi file.

Do not use `saga_import_xml` (Import date / purchases). Do not use
`saga_import_incasari_xml` for invoices.

Restart Markus MCP if `list_tools` is missing `saga_add_iesire`.
