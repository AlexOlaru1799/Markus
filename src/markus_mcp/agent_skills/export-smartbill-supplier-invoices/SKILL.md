---
name: export-smartbill-supplier-invoices
description: >-
  List and export SmartBill supplier invoices (Documente furnizori) for a user
  period, then convert the spreadsheet to SAGA Facturi XML. Use when the user
  asks for SmartBill achizitii, documente furnizori, supplier invoices, an
  Excel/XLS export, or a SAGA XML import file from those documents.
---

# Export SmartBill supplier invoices

Use Markus MCP (`user-markus`). Credentials come from `private.data` — never ask
the user to paste the API token or password into chat.

## Checklist

```
- [ ] 1. smartbill_status
- [ ] 2. Map the user's period → date_from/date_to or period=
- [ ] 3. smartbill_list_supplier_invoices
- [ ] 4. smartbill_export_supplier_invoices_xls
- [ ] 5. smartbill_invoices_to_saga_xml (same period, or xls_path from step 4)
- [ ] 6. Reply with XLS path, XML path, invoice_count, skipped_ro, skipped_no_nir
- [ ] 7. Full pipeline into SAGA → skill `smartbill-to-saga-import`
```

If the user already has a Documente furnizori `.xls` / `.xlsx`, skip 3–4 and call
`smartbill_invoices_to_saga_xml` with `xls_path`.

## Period

Prefer the tool's `period` when it fits:

- this month → `period="this_month"` (1st of month through today)
- last month → `period="last_month"`
- otherwise pass `date_from` / `date_to` as `YYYY-MM-DD`
- "from 15 September" → `date_from` that day (current year unless specified), `date_to` today

List/export use SmartBill Cloud **Documente furnizori** (`saved_only` Salvate + Nesalvate, dates as `DD/MM/YYYY`). If `count` is 0, check `screenshot_path` — the period control must not still say "Luna curenta" when last month was requested.

**Salvate vs Nesalvate:** "invoices from last month" means document date in that month on **Salvate** (ignore-dates off). **Nesalvate** + "Ignoră data documentului" is a different queue and will not match that list.

Reload the Markus MCP server after code changes before calling the tools again.

## SAGA XML rules (from the invoices processor)

`smartbill_invoices_to_saga_xml` matches the Flask `process_invoices_to_xml` task:

- Header row is the first row containing both NIR and CIF
- Drop rows with empty NIR
- Group by `Document furnizor`
- Skip invoices whose CIF starts with `RO` (Romanian suppliers)
- Dates become `DD.MM.YYYY`; RON gets `<Curs>1.0000</Curs>`
- NIR is written as `<Descriere>`
- Filename: `F_<companyCIF>_<DD>_<MM>_<YYYY>.xml` (SAGA Import date). CIF digits only, no `RO`. Date is the period end when known, otherwise the latest invoice date. Example: `F_1235556_15_07_2026.xml`

A large XLS with mostly RO CIF will correctly produce few or zero XML invoices. Report `skipped_ro` and `skipped_no_nir` so that is not a surprise.

To load the XML into SAGA Import date as part of SmartBill export+import, use
the `smartbill-to-saga-import` skill. For an XML path the user already has, use
the `import-xml-to-saga` skill.

Stripe / Woo / Trendyol / balanță / recepții processors from the old Flask app are **not** MCP tools.

## If status/login fails

- Missing token → `smartbill_token` in `~/.markus/private.data` or rerun installer
- Missing Cloud password → `smartbill_password` (or `saga_password` as fallback)
- Missing CIF only blocks `GET /series`, not list/export
