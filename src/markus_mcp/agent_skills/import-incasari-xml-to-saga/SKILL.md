---
name: import-incasari-xml-to-saga
description: >-
  Import a SAGA Încasări or Plăți XML on Jurnal de Bancă and associate each
  receipt to unpaid Ieșiri of the matching clients via SAGA DisplayData(cod).
  Use when the user gives an .xml / I_*.xml / P_*.xml path, or an
  <Incasari>/<Plati> file, and asks to import it into SAGA Jurnal de Bancă /
  JurnalDeBanca / Import extrase, or to associate încasări / plăți / bank
  receipts with Ieșiri / invoices / clients.
---

# Import bank XML → Jurnal de Bancă → Asociere

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

Trigger on this flow only:

1. User gives an **`.xml`** (typically `I_<dd>_<mm>_<yyyy>.xml` / `P_…`)
2. Open **Jurnal de Bancă** (`https://web2.sagasoft.ro/sagac/JurnalDeBanca`)
3. Import the XML on **Import extrase**
4. Associate via SAGA's own path: `GetTableExtraseDet().DisplayData(codFactura)`
   then `UpdateDateExtraseDet` (same persist as Asociere automata). The toolbar
   button calls `DisplayData()` with no client code, so the invoice grid stays
   empty on multi-client files. For `P_*.xml`, SAGA matches **Intrări**.

This is **not** `saga_import_xml` (Import date / purchases) and **not**
`saga_import_iesiri_xml` (create sales invoices).

## Checklist

```
- [ ] 1. saga_status / saga_login (pause for email auth / OTP if needed)
- [ ] 2. saga_import_incasari_xml(xml_path, confirm_write=false, asociere=true)
- [ ] 3. After explicit user OK → saga_import_incasari_xml(..., confirm_write=true, asociere=true)
- [ ] 4. Report row_count, updated_tert, associated_count, asociere_result.message
```

`xml_path` is the file the user named. Do not rename it. `asociere` stays
`true`. Pass `partner=` only if the user named **one** client/supplier for
every row. Otherwise omit it — the tool sets tert/CodFactura from the Ieșiri
(or Intrări) whose `NrDoc` matches `<FacturaNumar>`, then SAGA associates.

Pass `account=` only if the user named a treasury analytic. Default is XML
`<Cont>` (example `5125.8`).

## Confirm gate

The user's "import this XML" does **not** skip `confirm_write=false`. Show
line_count, total_amount, dates, account, and warnings. Only call
`confirm_write=true` after they say yes.

Do not call `saga_reset_session` with `delete_profile=true`.

If `list_tools` is missing `saga_import_incasari_xml`, restart Markus MCP.
