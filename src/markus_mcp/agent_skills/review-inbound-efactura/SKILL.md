---
name: review-inbound-efactura
description: >-
  List and download SAGA WEB e-Factura rows via Markus MCP saga_efactura_list /
  saga_efactura_download. Use when the user asks to review e-Facturi, SPV inbox,
  facturi primite/emise from e-Factura. Never submit or cancel to ANAF unless the
  user explicitly asks and confirms with the gated phrase.
---

# Review inbound e-Factura (no auto-submit)

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

**Read-only by default.** Do **not** call `saga_efactura_submit`,
`saga_efactura_cancel`, or save an SPV token unless the user explicitly asked
to send/cancel to ANAF **and** confirmed the preview.

SAGA WEB historically could **send issued invoices** before inbound supplier
import was fully migrated. If the list is empty or the screen is missing, say so
and do not invent rows. Desktop SAGA C may still be required for some inbound
imports.

## Checklist

```
- [ ] 1. saga_status / saga_login
- [ ] 2. saga_efactura_list — show number, date, partner, status, index
- [ ] 3. Optional: saga_efactura_download(invoice_id) for XML/PDF
- [ ] 4. Summarize for the user. Stop.
```

## Gated ANAF (only if the user explicitly asks)

Preview first (`confirm_write=false`). After they OK **this invoice**:

- Submit: `confirm_write=true` and `confirm_phrase='TRIMITE EFACTURA'`
- Cancel: `confirm_write=true` and `confirm_phrase='ANULEAZA EFACTURA'`

Never guess the phrase. Never run these unattended.

Restart Markus MCP if `list_tools` is missing `saga_efactura_list`.
