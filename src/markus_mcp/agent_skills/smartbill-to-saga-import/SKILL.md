---
name: smartbill-to-saga-import
description: >-
  Log in to SmartBill if needed, list Documente furnizori for a user period,
  export .xls, convert to SAGA Facturi XML, log in to SAGA if needed, and
  import the XML on Import date. Use when the user asks to put SmartBill
  achizitii / supplier invoices / documente furnizori into SAGA, import last
  month into SAGA, or run the SmartBill → XLS → XML → SAGA pipeline.
---

# SmartBill supplier invoices → SAGA Import date

Run this **end-to-end** with Markus MCP (`user-markus`). Do not skip tools.
Do not use Flask, pandas, or ad-hoc scripts — the converter is
`smartbill_invoices_to_saga_xml`.

Credentials stay in `private.data`. Never ask the user to paste tokens or
passwords.

The user's request to run this pipeline **authorizes** the SAGA XML import.
Still call `saga_import_xml` with `confirm_write=false` first, then immediately
`confirm_write=true` unless the preview shows a clear problem (stop and ask).

If `list_tools` is missing `saga_import_xml` or `smartbill_invoices_to_saga_xml`,
stop and tell the user to restart Markus MCP (Settings → MCP → markus → restart,
or bump `MARKUS_MCP_CATALOG` in `~/.cursor/mcp.json`).

## Checklist

```
- [ ] 1. smartbill_status
- [ ] 2. Map period → period= or date_from/date_to
- [ ] 3. smartbill_list_supplier_invoices
- [ ] 4. smartbill_export_supplier_invoices_xls  (same period + section)
- [ ] 5. smartbill_invoices_to_saga_xml(xls_path from step 4)
- [ ] 6. saga_status → saga_login / saga_submit_otp if needed
- [ ] 7. saga_import_xml(xml_path, confirm_write=false)
- [ ] 8. saga_import_xml(xml_path, confirm_write=true)
- [ ] 9. Tell the user where the docs landed in SAGA
```

## Step 1 — SmartBill credentials / “login”

Call `smartbill_status` with no arguments.

- `token_configured` + `password_configured` (or saga password fallback) → continue.
- Missing token → `smartbill_token` in `~/.markus/private.data`.
- Missing Cloud password → `smartbill_password` or `saga_password`.
- Missing CIF only blocks `GET /series`, not list/export.

There is **no** separate SmartBill login tool. Cloud UI login happens inside
`smartbill_list_supplier_invoices` / `smartbill_export_supplier_invoices_xls`.

## Step 2 — Period

| User says | Tool args |
|---|---|
| this month / luna curentă | `period="this_month"` |
| last month / luna trecută | `period="last_month"` |
| explicit range | `date_from` + `date_to` as `YYYY-MM-DD` |
| from 15 September | `date_from` that day, `date_to` today |

Use **`section="saved"`** (Salvate, document date in range). That is “invoices
from last month”. Do **not** use Nesalvate / ignore-dates unless the user asks
for that queue.

Use the **same** `period`/`date_from`/`date_to`/`section` on list, export, and
convert.

## Step 3 — List

```
smartbill_list_supplier_invoices(period="last_month", section="saved")
```

(or `date_from`/`date_to` instead of `period`)

If `count` is 0, check `screenshot_path` — the period control must not still say
“Luna curenta” when last month was requested. Fix and retry before export.

Show the user `count` (and `section_counts` if present). Continue unless they
wanted a different period.

## Step 4 — Export .xls

```
smartbill_export_supplier_invoices_xls(period="last_month", section="saved")
```

Keep `path` from the result (under `~/.markus/data/smartbill/`). That file is the
spreadsheet to convert.

## Step 5 — Convert to SAGA XML

```
smartbill_invoices_to_saga_xml(xls_path="<path from step 4>")
```

Pass `date_to` when known so the filename uses the period end:

```
smartbill_invoices_to_saga_xml(xls_path="…", date_to="YYYY-MM-DD")
```

Do not pass `period` here if you already have `xls_path` — that would export
again.

Converter rules (do not reimplement):

- Keep rows with NIR; skip empty NIR
- Skip CIF starting with `RO`
- Filename: `F_<cif>_<dd>_<mm>_<yyyy>.xml`

Keep `path` / `filename` / `invoice_count` / `skipped_ro` / `skipped_no_nir`.
If `invoice_count` is 0, stop — nothing to import.

## Step 6 — SAGA login

```
saga_status()
```

If `logged_in` and `firm_selected` → step 7.

Otherwise:

```
saga_login()
```

- `needs_browser_authorization=true` → tell the user to click **Autorizează
  browser** in the SAGA email (not “Autentificare fără autorizare”), then
  `saga_login` again.
- `needs_otp=true` → ask for the 6-digit code, then
  `saga_submit_otp(code="……")`.
- Do **not** set `allow_otp_without_authorization=true` unless they ask.
- Do **not** call `saga_reset_session(delete_profile=true)`.

Check the login screenshot / `DenumireFirma`. If it is the wrong company, stop
and ask — `saga_login` selects the first firm on `/Firme`.

## Step 7 — Preview import

```
saga_import_xml(xml_path="<path from step 5>", confirm_write=false)
```

Expect `requires_confirmation=true`. Show filename, `invoice_count`,
`total_amount`, `warnings`.

## Step 8 — Import

```
saga_import_xml(xml_path="<path from step 5>", confirm_write=true)
```

Report `stare_import`, `destinatie`, `message`, `screenshot_path`, `report_path`.

`Importat partial` is OK if only some invoices failed (empty CIF, etc.). Quote
failed `nrDoc` from `response.data` or `report_path`.

## Step 9 — Where to look in SAGA

These XML files land in **Operații → Intrări valută**
(`https://web2.sagasoft.ro/sagac/IntrariValuta`), **not** Intrări and **not**
Ieșiri — even RON rows, because the XML has `<FacturaMoneda>` / `<Curs>`.

Also: **Diverse → Import date** shows the file as Importat / Importat partial.

## Do not

- Invent XML or rename `F_*.xml` unless asked
- Import Stripe / Woo / Trendyol processors (not MCP tools)
- Skip `confirm_write=false`
- Call `saga_reset_session` with `delete_profile=true`
