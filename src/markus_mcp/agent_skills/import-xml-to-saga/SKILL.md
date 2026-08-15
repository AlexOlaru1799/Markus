---
name: import-xml-to-saga
description: >-
  Upload a SAGA Facturi XML on Import date (web2.sagasoft.ro/sagac/ImportDate)
  via Markus MCP saga_import_xml. Use when the user provides an XML path and
  asks to import it into SAGA (Import date, ImportDate, F_*.xml, Facturi XML).
---

# Import XML into SAGA Import date

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

This writes purchase invoices onto **Intrări valută** (not Intrări / Ieșiri)
when the XML has `<FacturaMoneda>` / `<Curs>`. Preview first, then import only
after the user explicitly OK.

For SmartBill list → XLS → XML → import, use the `smartbill-to-saga-import` skill.

## Checklist

```
- [ ] 1. saga_status / saga_login (pause for email auth / OTP if needed)
- [ ] 2. saga_import_xml(xml_path, confirm_write=false) — show preview
- [ ] 3. After explicit user OK → saga_import_xml(..., confirm_write=true)
- [ ] 4. Report stare_import, destinatie, screenshot_path, report_path
```

## Path

`xml_path` is the file the user named (or the SmartBill converter output
`F_<cif>_<dd>_<mm>_<yyyy>.xml` under `~/.markus/data/smartbill/`). Do not rename
it unless they ask. Warn if the name is not `F_*.xml`.

For `I_*.xml` / `P_*.xml` (`<Incasari>` / `<Plati>`), use
`import-incasari-xml-to-saga` / `saga_import_incasari_xml` on Jurnal de Bancă,
not this skill.

For RON **sales Ieșiri** Facturi XML (your firm as Furnizor, customers as
ClientNume/ClientCod, extra `<Cont>` / `<TVAProc>`), use
`import-iesiri-xml-to-saga` / `saga_import_iesiri_xml`. That tool posts
`Iesiri/Create_Iesiri` so `NrDoc` stays `FacturaNumar`. This skill is Import
date (typically Intrări valută).

## Login

Same as other SAGA tools: `saga_status`, then `saga_login`. If
`needs_browser_authorization`, tell them to click **Autorizează browser** in
email, then login again. If `needs_otp`, ask for the 6-digit code and
`saga_submit_otp`.

## Confirm gate

The user's "import this XML" does **not** skip `confirm_write=false`. Show
invoice_count, filename, totals, warnings. Only call `confirm_write=true` after
they say yes.

Do not call `saga_reset_session` with `delete_profile=true`.

Reload the Markus MCP server after code changes before calling the new tool.
