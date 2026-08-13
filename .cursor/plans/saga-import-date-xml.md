# SAGA Import date XML tool

Goal: MCP tool `saga_import_xml` that opens
[Import date](https://web2.sagasoft.ro/sagac/ImportDate), uploads a user-provided
Facturi XML, and runs SAGA's import.

Ground truth is `~/.markus/data/saga/research/modules/ImportDate.js`.

## Flow (matches the UI)

1. Hidden `#fileInputXML` → `FormData.append("files", …)` → POST
   `ImportDate/UploadXMLFiles` → `location.reload()`.
2. Grid row: `FisierSursa`, `Destinatie` (Intrări / Ieșiri / Articole),
   `StareImport` (1 Neimportat … 5 Importat).
3. POST/GET `ImportDate/ImportFactura` with `{fileName, destinatie}`.
4. On error/partial/warnings: `ImportDate/GetResultImportTXT`.

## Guardrails

- `confirm_write=false` preview (parse XML, count invoices, warn on filename).
- `confirm_write=true` only after explicit user OK.
- If the file is already **Importat**, do not re-import; ask the user to cancel
  in SAGA first.
- Do not auto-answer unrelated Choice modals (ImportFactura itself does not use
  Choice; AnuleazaImportXML does).

## Status

Implemented in `src/markus_mcp/tools/saga/import_date.py`, registered as
`saga_import_xml`. Skill: `.cursor/skills/import-xml-to-saga/SKILL.md`.
