---
name: import-purchase-invoice-to-saga
description: >-
  Put a purchase invoice into SAGA WEB Intrări via Markus MCP saga_add_intrare
  from chat fields or a readable PDF. Use when the user asks to add/create an
  Intrare / factură furnizor (single document). For bulk SmartBill / NIR XML
  with many suppliers, use saga_import_xml on Import date instead.
---

# Purchase invoice any source → SAGA Intrări

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

One posting path: **`saga_add_intrare(header, lines)`**. Non-RON `Valuta` uses
Intrări valută (`GetCursValutar` fills Curs when omitted).

**Bulk NIR** (many FurnizorNume in one Facturi XML, SmartBill pack) still goes
through **`saga_import_xml`** / Import date — do not loop `saga_add_intrare`
for those files unless the user asked for one invoice.

## Checklist

```
- [ ] 1. Detect source: chat / PDF / single Facturi XML vs bulk NIR
- [ ] 2. Bulk NIR → saga_import_xml skill (Import date), stop
- [ ] 3. saga_status / saga_login
- [ ] 4. Ensure supplier exists (saga_search_suppliers / saga_create_supplier).
      The adapter resolves Furnizori on confirm and **aborts if missing** (no auto-create).
- [ ] 5. Map Furnizor or Cod, Data, NrDoc, lines with Cont
- [ ] 6. saga_add_intrare(..., confirm_write=false)
- [ ] 7. After explicit user OK → confirm_write=true
```

Never invent Cont, Gestiune, or prices. Pass only user-specified fields.

Restart Markus MCP if `list_tools` is missing `saga_add_intrare`.
