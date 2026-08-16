# SAGA WEB → Markus: ingest, engine, named tools, and skills

Goal: cover **as much of SAGA WEB as is safe to automate**, with **as little human intervention as possible**, without turning Markus into 77 MCP tools or a generic CRUD API.

SAGA’s menu (`data/saga/research/feature_inventory.json`, 77 items) is a **menu**, not 77 independent APIs. Many rows share one controller. Coverage is measured as:

1. **Schema catalog** — local copy of each onboarded SAGA **grid** (`tableModel` / `tableColumns`), keyed by operation. When the user says “do X” with data in any format, we look up X’s expected fields and map into them.
2. **Ingest** — turn chat / XML / PDF / XLS into a **canonical document** that matches that schema (aliases, types, required vs optional).
3. **Engine** — one AdvancedControls client that can talk to any grid.
4. **Named MCP tools** — accountant verbs that accept **canonical documents**, not file formats (`saga_add_iesire`, `saga_add_iesiri_valuta`, `saga_post_bank_entries`, …).
5. **Agent skills** — multi-step jobs that pick an ingest path, then call those tools.

XML is a **common input**, not the tool contract. If the canonical shape looks like a Facturi header+lines JSON (or we serialize it to SAGA Facturi XML only when talking to Import date), that is an implementation detail. The user must be free to paste fields in chat, attach a PDF, or drop an `.xml`.

This document is the source of truth for protocol, code layout, MCP surface, skills, feature mapping, runbook, guardrails, waves, and the **master checklist (§13)** for “100% of SAGA” as defined there.

Do **not** drive rollout from `feature_inventory_compact.json` `t:` tags. That file is stale (it still marks IesiriValuta as unsolved and Import date as human-only). Use this plan + the live tool catalog. Tick boxes in **§13** as work lands.

---

## 0. Executive summary

SAGA WEB is an ASP.NET MVC app whose data layer is one generic grid (`AdvancedControls.min.js`, `AdvancedTable`). Every nomenclator, journal and document screen is an instance of that grid driven by a JSON `tableModel`.

That means we do **not** clone `partners.py` 70 times. Internally we need:

1. **Schema catalog** — committed snapshots of probed `tableModel`s (and report `auxiliar` filters) so ingest can look up “what does operation X expect?” without guessing and without a live SAGA round-trip.
2. **Canonical documents** — format-agnostic payloads (invoice, bank entries, partner, …) whose keys **are** those schema fields (plus a small alias map). Named SAGA tools consume these.
3. **Ingest parsers / mappers** — one parser per *input* format; then a **schema mapper** that matches user keys (`ClientNume`, “customer”, “client”) onto `tableColumns[].name`. Chat/PDF extraction fills the same schema.
4. **One grid client** (read / create / edit / delete / next-index / master-detail / export).
5. **One discovery layer** that reads `tableModel` live and **refreshes** the catalog when SAGA changes.
6. **One report client** for the `Rapoarte/*` two-step PDF/XLS pipeline.
7. **Thin adapters** only where a screen has extra business endpoints (`GetCursValutar`, `ExecutaValidare`, `GetNrDoc`, e-Factura, Import extrase, …).

**Do not dump the SAGA SQL database.** WEB never gives us CREATE TABLE. The real schema for MCP is `tableColumns` (+ combos, defaults, required/hidden/lock) on each AdvancedControls grid, plus document pairs (header table + detail table). Copy **those** locally, one screen at a time as we onboard — not all 77 menus on day one, and not payroll/admin tables we will never write.

What we do **not** need:

- Exposing the generic grid client as employee MCP tools.
- Making `xml_path` the primary API for creating invoices or bank rows. Today’s `saga_import_iesiri_xml` / `saga_import_incasari_xml` stay as **convenience wrappers** that parse → call the document tools; new work goes through canonical documents.

**Wave 0** extracts the engine from code we already have (`partners.py`, `iesiri_valuta.py`, `iesiri.py`, `wipe.py`, `jurnal_banca_import.py`), with **zero employee tool-name changes**. Later waves add documents + ingest, then named tools + a skill per job.

Shipped today (keep names stable; evolve inputs over waves):

| Area | Tools | Input today | Target input |
|---|---|---|---|
| Session | `saga_status`, `saga_login`, `saga_submit_otp`, `saga_reset_session` | — | — |
| Clienti | `saga_*_partner` | field dicts | unchanged (already format-agnostic) |
| FX sales | `saga_add_iesiri_valuta` | `header` + `lines` dicts | unchanged — **this is the model** |
| RON sales | `saga_add_iesire` / `saga_import_iesiri_xml` | header+lines, `document`, or Facturi XML | `saga_add_iesire` is the write; XML is ingest |
| Bank | `saga_post_bank_entries` / `saga_import_incasari_xml` | BankBundle, chat rows, or I_/P_ XML | same Import extrase worker |
| Purchases | `saga_add_intrare` (single) / `saga_import_xml` (bulk NIR) | header+lines or Facturi XML | bulk stays Import date |
| Wipe | `saga_wipe_data` | targets | unchanged |

Skills already in `src/markus_mcp/agent_skills/` (installed to `~/.cursor/skills/` on `--setup`): FX PDF, SmartBill → XML → Import date, Ieșiri XML, încasări XML, wipe, period pack, sales/purchase/bank any-source, casă entry.

---

## 1. Target product architecture

Markus splits **schema lookup** (operation → expected fields), **ingest** (any user format → those fields), **operations** (MCP tools), and **jobs** (agent skills).

```
Accountant: “do X” + (chat | .xml | PDF | XLS)
        │
        ▼
┌───────────────────────────────────────┐
│  Skills                               │
│  resolve X → operation / document kind│
└───────────────────┬───────────────────┘
                    ▼
┌───────────────────────────────────────┐
│  Schema catalog (local)               │
│  schemas/iesiri.json = tableColumns   │
│  + aliases, required, combos          │
└───────────────────┬───────────────────┘
                    │ expected fields
        ┌───────────┴───────────┐
        ▼                       ▼
┌──────────────────┐   ┌────────────────────────┐
│ Ingest parsers   │   │ Agent extracts values  │
│ XML / XLS → raw  │   │ from chat / PDF        │
└────────┬─────────┘   └───────────┬────────────┘
         │                         │
         └───────────┬─────────────┘
                     ▼
         Schema mapper
         user keys → tableColumns names
         validate required / types
                     ▼
         Canonical document
                     ▼
┌───────────────────────────────────────┐
│  Named MCP tools (confirm_write)      │
└───────────────────┬───────────────────┘
                    ▼
         SAGA engine → one Chromium session
```

### 1.1 Five layers

| Layer | Lives in | Allowed to know | Not allowed |
|---|---|---|---|
| **Schema catalog** | `tools/saga/schemas/*.json` + `schema.py` | `tableColumns`, aliases, required, combos, header/detail pairing | Playwright at lookup time; inventing columns |
| **Ingest** | `tools/saga/documents/` | Input formats + catalog aliases | Playwright, `_CHECKED`, SAGA routes |
| **Engine** | `protocol.py`, `grid.py`, … | `tableModel`, `RowData`, routes | file formats, WhatsApp, PDF OCR |
| **Named tools** | `server.py` + wrappers | Canonical documents, `confirm_write` | Parsing XML/PDF; multi-step jobs |
| **Skills** | `agent_skills/<job>/SKILL.md` | User intent → operation X → catalog + tools | Re-implementing SAGA HTTP |

WhatsApp and SmartBill stay sibling packages. Skills may call them. SmartBill’s XLS→Facturi XML converter is an **ingest** (or emit) step into the same canonical invoice, not a reason for SAGA tools to require XML.

### 1.2 Schema catalog (local lookup for operation X)

This is the “copy SAGA schemas locally” piece — **yes, it makes sense**, with a precise meaning:

| Copy this | Do not copy this |
|---|---|
| Each onboarded grid’s `tableModel`: `tableName`, `primaryKey`, `tableColumns[]` (name, inputType, selectModel, defaultValue, hidden/lock), `actionsURLs`, master/detail pairing | SAGA SQL Server / Firebird table dumps (WEB does not expose them) |
| Alias maps (RO labels, XML tags, English chat synonyms → column `name`) | Every menu item on day one (Salariati, Inchidere luna, … until we have a job) |
| Report `auxiliar` filter schemas when Wave 2 lands | Binary `.mdf` / firm data |

**Flow when the user says “add this as an Ieșire” and pastes anything:**

1. Skill maps the request to operation `iesiri` (or document kind `sales_invoice`).
2. `schema.py` loads `schemas/iesiri.json` + `schemas/iesiri_detalii.json` (committed snapshot from a reviewed probe).
3. Ingest/mapper: match incoming keys to columns via exact name, then aliases (`ClientNume` → `Client`, “qty” → `Cantitate`). Unknown keys → `unknown_fields` (do not send). Missing required (non-hidden, no default) → ask the user.
4. Canonical document uses **SAGA column names** so the adapter does not guess.
5. Optional live refresh: if `saga_probe_screen` shows the snapshot drifted, CI / Wave runbook updates the JSON. Runtime may merge a fresh `tableModel` for reads; **writes use the committed catalog** until a human reviews the diff (avoids silently posting a renamed column).

Canonical document types (`SalesInvoice`) are a **facade** over one or more catalog tables (header + lines), not a second invented schema. If the catalog and the facade disagree, the catalog wins.

`saga_describe_screen` / `saga_partner_fields` / `saga_iesiri_valuta_fields` become thin reads of this catalog (today those catalogs are hand-written in Python — migrate them into JSON snapshots).

### 1.3 Canonical documents (format-agnostic tool input)

Named write tools speak **documents**, not paths.

Sketch (field names **come from the schema catalog**, not from us inventing JSON):

```python
# tools/saga/documents/types.py  (conceptual)

SalesInvoice = {
  "kind": "sales_invoice",          # or "sales_invoice_fx"
  "currency": "RON" | "EUR" | …,
  "header": { "Client"|"Cod", "Data", "NrDoc", "Scadent", "Valuta"?, … },
  "lines":  [ { "Cont", "Denumire", "Cantitate", "PretUnitar…", "TVA_ART", … } ],
  "meta":   { "source": "chat"|"facturi_xml"|"pdf"|"smartbill_xls", "source_path"?: str },
}

BankBundle = {
  "kind": "bank_receipts" | "bank_payments",
  "account"?: str,
  "entries": [ { "date", "amount", "partner"?, "factura_numar"?, … } ],
  "meta": { "source": "chat"|"incasari_xml"|… },
}
```

Rules:

- **Schema first.** Every named write looks up the catalog for that operation before mapping. No ad-hoc column lists in adapters once the snapshot exists (adapters keep only side-effect POSTs).
- **SAGA tools only accept documents (or field dicts already shaped like today’s FX tool).** They must not require `xml_path` to create an Ieșire.
- **Ingest is many → one.** Facturi XML, chat, PDF extraction, SmartBill rows all produce `SalesInvoice`.
- **Emit is optional.** If we still use SAGA Import date (upload Facturi XML), a small `documents/emit_facturi_xml.py` turns canonical → XML for that *transport*. That does not make XML the user-facing contract.
- **Proven pattern already:** `saga_add_iesiri_valuta(header, lines)` is format-agnostic. The FX PDF skill extracts into those dicts. RON Ieșiri and bank should converge on the same idea.
- **Compatibility:** keep `saga_import_iesiri_xml(xml_path)` / `saga_import_incasari_xml(xml_path)` as thin wrappers: parse XML → document(s) → call `saga_add_iesire` / `saga_post_bank_entries`. Skills and docs prefer the document tools + ingest.

### 1.4 MCP surface rules

**Employee tools (always):**

- Session: `saga_status`, `saga_login`, `saga_submit_otp`, `saga_reset_session`, **`saga_context`** (new).
- Named verbs on **documents / field dicts**: `saga_create_partner`, `saga_add_iesiri_valuta`, then `saga_add_iesire`, `saga_add_intrare`, `saga_add_casa_entry`, `saga_post_bank_entries`, `saga_run_report`, `saga_efactura_list`, …
- **Ingest helpers** (read-only / pure transform, no SAGA write): e.g. `saga_parse_facturi_xml`, `saga_parse_incasari_xml` — return canonical documents + validation errors so the agent can show a preview before `confirm_write`. Optional; skills may also call Python via the same modules if we only expose parse inside the write preview.
- Convenience wrappers that take a path: `saga_import_iesiri_xml`, `saga_import_incasari_xml`, `saga_import_xml` (Import date upload) — keep for existing skills; implement as parse/emit + document tool or Import date transport.
- Wipe: `saga_wipe_data`.

**Generic reads (employee, once Wave 0 exists):**

- `saga_list_screens`, `saga_describe_screen` (catalog dump: columns, required, aliases, combos), `saga_list_rows`, `saga_get_row`, `saga_lookup`, `saga_export_grid`, `saga_run_report`.

**Generic writes (`saga_create_row`, …):** engine only; not on employee MCP.

**Probe:** developer onboarding only (`saga_probe_screen`).

### 1.5 Skills rules

- One skill per **job**, not per SAGA menu item and not per file type.
- Prefer **one skill per document kind** that accepts any source: “put this sales invoice in SAGA” whether the user pasted fields, attached PDF, or gave `F_*.xml`.
- Skill steps: (1) detect operation X → (2) load schema catalog → (3) ingest or extract → (4) map/validate against catalog → (5) preview → (6) named tool `confirm_write=false` then `true`.
- Source of truth: `src/markus_mcp/agent_skills/`. `--setup` copies via `cursor_skills.py`.

| Skill | Needs |
|---|---|
| `import-fx-invoice-to-saga` | exists (PDF → header/lines → `saga_add_iesiri_valuta`) — template for others |
| `smartbill-to-saga-import` | exists; evolve to SmartBill → canonical → Import date emit or `saga_add_intrare` |
| `export-smartbill-supplier-invoices` / `import-xml-to-saga` | exist (export-only / Import date XML) |
| XML-named skills (`import-iesiri-xml-to-saga`, `import-incasari-xml-to-saga`) | keep until document tools land; then retarget to parse + `saga_add_*` |
| Sales invoice (RON) any source | `saga_add_iesire` + Facturi XML parser + chat/PDF extract |
| Bank entries any source | `saga_post_bank_entries` + I_/P_ parser + chat |
| Cash receipt | `saga_add_casa_entry` |
| Period pack | `saga_run_report` + `saga_context` |
| Inbound e-Factura review | `saga_efactura_list` (submit stays human) |
| `wipe-saga-data` | exists |

### 1.6 What “100% of SAGA” means here

| Band | Target |
|---|---|
| Engine can read any grid we have probed | Yes |
| Engine can write nomenclators + documents that have an adapter | Yes |
| Accountant can supply data as chat, XML, PDF, or XLS for those jobs | Yes — schema lookup → ingest → canonical → named tool |
| Schema catalog covers every **onboarded** write/read screen | Yes — grows with waves; not a one-shot dump of all SAGA |
| Agent can finish common jobs unattended after login/OTP | Yes, via skills |
| ANAF filings, payroll execute, month close, users, DB, special stock ops | **Read + hard-gated human confirm only** |
| Zero human forever | No — OTP, SPV, legal filings stay side-channels |

Count **controllers + jobs automated**, not 77/77 menu ticks. Count **input formats** as parsers, not as separate MCP tools.

---

## 2. Protocol reference (reverse-engineered)

Confirmed from `data/saga/research/AdvancedControls.min.js`, `Layout.min.js`, `modules/*.js`, and live captures in `data/saga/network-*.json`. Runtime session dir is **`~/.markus/data/saga-session`**, not `./data/saga-session`.

### 2.1 Session and transport

| Concern | Value |
|---|---|
| Login origin | `https://web.sagasoft.ro` (`SAGA_BASE_URL`) |
| App origin after firm connect | `https://web2.sagasoft.ro/sagac` (`SAGA_APP_BASE_URL`) |
| Report/API origin | `document.body.dataset.api` at runtime — **do not hardcode** |
| Auth | persistent Chromium profile under `~/.markus/data/saga-session` |
| Headers | `X-Requested-With: XMLHttpRequest`, `X-SAGA-Valid-Token: <cookie SAGA-Valid-Token-JS>` via `saga_session._auth_headers(page)` |
| Calls | `page.request.get/post/fetch` on the logged-in page (cookies shared) |
| Concurrency | **one** SAGA browser worker (`session._run_on_browser_thread`). Do not add a second context. |

Context endpoints (feed `saga_context`):

- `GET Home/LoadOperationalData` — firm (`Toolbar.CodFirma`), user, `Societ`, `Configurare`, `TipContabilitate`, `FaraStocuri`, working interval.
- `GET Home/LoadDrepturiEcrane`, `Home/GetDreptEcran`, `Home/GetDreptCont` — rights.
- `GET Home/IsStillConnected` — cheaper than a screenshot.
- `GET Home/GetTipContabilitate`, `Home/GetCurrentUser`, `Home/GetDatabaseSize`, `Home/CheckDBStatus`.

### 2.2 `tableModel`

`AdvancedControls.parseTableModel()`:

```js
tableName, controllerName, primaryKey,
detailSetup.{masterTableName, isMaster, isDetail, selectionKey},
tableConfig.actionsURLs.{getData, create, edit, delete, getNextIndex, copyDetail, deleteMasterDetails},
tableColumns[]  // name, inputType, selectModel, defaultValue, …
```

- Never guess CRUD URLs: open the screen, read `tableModel`.
- Never guess `RowData` keys: `tableColumns[i].name`.
- DOM: `#containerAdvancedTable_<TableName>`, `#tableMain_<TableName>`, `.buttonOperationAdd_<TableName>`, …
- `page.evaluate`: `getTable("<TableName>")` → `GetVirtualData`, `GetRequestSetup`, `ToolbarActionSave`, … `tabID` is `SenderID`.

Probe **does not** replace adapters. Side-effect endpoints (`GetCursValutar`, `ExecutaValidare`, `IncarcaExtras`, …) live in module JS and in captured XHR, not in `actionsURLs`.

### 2.3 Read (`getData`)

```
GET actionsURLs.getData  ? RequestSetup = JSON.stringify(requestSetup.json)
→ { data: [...rows...], pageCount: n }
```

Working `RequestSetup` already used in `partners.py` / `iesiri_valuta.py` / `wipe.py` / `jurnal_banca_import.py`:

| Key | Meaning |
|---|---|
| `Skip`, `BatchSize` | paging |
| `GetRowsCount` | total count |
| `FilterKeyword` | search |
| `FilterColumns` | columns to search |
| `FilterSearchType` | 0 starts-with, 1 contains, 2 exact |
| `FilterCaseSensitive`, `FilterCurrentTable` | bool |
| `SortColumn`, `SortMode` | sorting |
| `Id` | single row / master PK for details (`wipe.py` already passes `master_id` this way) |
| `auxiliar` | screen-specific filters — **reports** |

Wave 0 should **unify this helper**, not block on a perfect `new DataRequestSetup().json` dump. Capture `auxiliar` per report when building `reports.py`.

### 2.4 Write (`create` / `edit`) — `RowData` + `_CHECKED`

**(a) Classic AdvancedControls** (documents, e.g. IesiriValuta):

```
POST actionsURLs.create | edit
  RowData, _CHECKED, SenderID, IsPaste, uvf
```

| `type` | Action |
|---|---|
| `Validation` | re-POST `_CHECKED=true` |
| `Choice` | re-POST `uvf=[{id, userChoice:"Yes"}]` **only if `confirm_write=true`**; echo the question |
| `Warning` | surface, do not retry |
| success | extract new PK |

Third variant: one `crudRequest` with `UserValidationFlags` and `CRUDOperation`.

**(b) Ex style** (Clienti):

```
POST Clienti/Create_Clienti | Edit_Clienti
  Data[<Column>]=…  _CHECKED  IsPaste  uvf
→ { success } | { errorCode: "ValidateData", validationFlags }
```

Generic client tries the family implied by the screen, falls back to the other. Already proven: `partners._post_clienti_row`, `iesiri_valuta._post_with_validation_retry`, `wipe._delete_ex` / `_delete_classic`.

### 2.5 Delete

UI uses **GET** with `{ Id, _CHECKED, SenderID }` (jQuery default). Clienti also accepts POST. Keep POST-then-GET. Master+details: `deleteMasterDetails`. After deleting a detail of Intrari/Iesiri (and valuta), refresh the master row. Wipe already encodes “children before header” and “day entries before day headers” for Jurnal de Bancă — that ordering belongs in the adapter/workflow, not in naive `grid.delete`.

### 2.6 PK, copy, master–detail

- `GET getNextIndex` unless `avoidPKGeneration`; always for Intrari/Iesiri (+valuta).
- Screen-specific: `Gestiuni/GetNextPK`, `Imobilizari/GetNrInventar`, `Transferuri/GetNrDoc`, `Contracte/GetNrContracte`, …
- `copyDetail` `{ originId, targetId, negative }` — copy document.
- Detail `getData` uses master PK as `RequestSetup.Id`; FK column is `detailSetup.selectionKey`. Document create: master → read PK → lines with FK → re-read master totals.

### 2.7 Lookups

`GET <Controller>/GetData_ComboBox_<selectModel>` with documented redirects to `Home` (conturi, proiecte, …). Column combo name is `tableColumns[i].selectModel` → `saga_lookup` is derivable.

### 2.8 Adapter-only endpoints (not in `tableModel`)

| Concern | Endpoints |
|---|---|
| Partner defaults | `Clienti/Verificare*`, `LProcedure_Clienti`, `Furnizori/…`, `Home/CheckCF`, `Home/GetBanca` |
| Chart of accounts | `PlanConturi/LProcedure`, `GetTipSintetic`, `VerifAnalitic121`, `Home/GetDreptCont` |
| Items / VAT / prices | `Articole/GetTVAArticol`, `IsVandabil`, `CheckSGR`, `GenereazaCB`, `GetBrut`/`SetBrut`, `PreturiVanzare/*`, `Home/GetTVA` |
| FX | `IntrariValuta/GetCursValutar` (IesiriValuta tool already uses the FX rate path) |
| Cash / bank | `RegistruCasa/SetActFact`, `GetClientByContAnalitic`, `SetContCasa`, `SetFiltruOP`, `IncarcaExtras`, `ImportExtrase/*` |
| Validare | `<Controller>/ExecutaValidare` + `Devalidare` (Intrari, Iesiri, IesiriValuta, Bonuri, Transferuri, Productie, Imobilizari, Inventariere, StateSalarii, InchidereLuna/…) |
| Accounting note | `Home/ExecutaInsMMod` after journal saves |
| Contracts | `Contracte/GenerareFacturi`, `CheckRate`, `GetNrContracte` |
| e-Factura | `EFactura/ReadToken`, `SaveToken`, `ImportEFactura`, `AnulareEFactura`, `LoadFacturiImport`, … |
| Import date | `ImportDate/UploadXMLFiles`, `ImportFactura` — **shipped** as `saga_import_xml` |
| Balance / close | `Balanta/ExecutaBalanta`, `InchidereLuna/*`, `Bilant/*` |
| DB | `BackupDB/*`, `Home/UpdateDB` |

### 2.9 Reports

```
POST Rapoarte/SetDataRaport<X>   Filtru, Titlu, Tip=Export, SortColumn, SortMode
GET  <apiBase>/Rapoarte/CreateRaport<X>?Filtru=Export&Descarca=true
```

Save `response.body()` only after `content-type` / magic bytes say PDF or XLS. HTML error pages must not be written as `.pdf`.

Setter inventory (from modules): Balanta, Bilant, Intrari, ListaIesiri, Articole, Imobilizari, Casa, OP, Deconturi, Inventariere, Productie, Consumuri, Contracte, StateSalarii, SitLunare, TransferuriNIR, … Creators: `BalantaPDF`, `IntrariPDF`, `ListaIesiri`, `JurnalBancaPDF`, `FacturaPDFNoDownload`, salary/bilant families, etc. Direct generators: `Bilant/GenerarePDF_Bilant`, `InchidereLuna/GenerarePDFDeclaratie`, …

Each report still needs its `auxiliar` filter schema. That is Wave 2 work, not “registry string only.”

### 2.10 Excel export

```
POST Home/ExportDate
  TableName, RequestSetup, Tip, RowsExport, …
```

One `saga_export_grid` for every registered grid.

---

## 3. Unknowns to capture (before / during the matching wave)

Do not block Wave 0 on these except where noted.

| ID | What | Recipe | Blocks |
|---|---|---|---|
| U1 | Full `DataRequestSetup.json` | `page.evaluate("() => JSON.stringify(getTable('Clienti').GetRequestSetup())")` | extra filter keys; paging already works |
| U2 | `tableModel` per screen | init-script hook on `JSON.parse` **or** scrape `#containerAdvancedTable_*` | generic reads; **do this as each screen is onboarded** |
| U3 | `tableColumns` extras | dump one real array | required / maxlength / caption |
| U4 | Report API base | `page.get_attribute("body", "data-api")` | reports |
| U5 | `SenderID` / `tabID` | already in `partners.py` / `iesiri_valuta.py` / `wipe.py` — **move to protocol** in Wave 0 | — |
| U6 | Per-report `auxiliar` | capture print-modal XHR or module `u.<Field>=` | `saga_run_report` |
| U7 | Rights matrix | `GET Home/LoadDrepturiEcrane` | **Probed:** Access=`0` = allowed, Access=`1` = restricted (Salariați / State salarii). `assert_writable` denies Access=1 and Adaugare/Stergere=0. |

Persist **reviewed** probes as committed catalog files under `src/markus_mcp/tools/saga/schemas/<table>.json` (packaged with the binary — not only gitignored `data/`). Raw captures may still live in `data/saga/research/tablemodels/` during a wave.

---

## 4. Code architecture

### 4.1 Layout (as shipped)

Named writes live at the `saga/` root. There is no `adapters/` package — extra POSTs (`GetCursValutar`, Import extrase, e-Factura) stay in the module that owns that job. SmartBill ingest is `tools/smartbill.py`, not `documents/from_smartbill.py`.

```
src/markus_mcp/tools/saga/
  session.py              # auth, browser thread, capture
  credentials.py
  protocol.py             # classify + handshake; SenderID; RequestSetup
  discovery.py            # tableModel extract + catalog diff
  grid.py                 # generic AdvancedControls client (not employee MCP)
  registry.py             # ScreenSpec: route, PK, risk, write_style, schema_id
  schema.py               # catalog load, aliases, map_fields(operation, payload)
  schemas/                # committed tableModel snapshots (onboarded screens only)
  documents/              # canonical payloads + ingest/emit (no Playwright)
    types.py
    validate.py
    parse_facturi_xml.py / emit_facturi_xml.py
    parse_incasari_xml.py / emit_incasari_xml.py
  reports.py / exports.py / lookups.py / context.py
  nomenclator.py          # Furnizori / Articole / casă via SagaGrid
  invoices.py             # saga_add_iesire / saga_add_intrare — one post_on_page
  bank.py                 # saga_post_bank_entries / saga_add_casa_entry
  iesiri_valuta.py        # FX extras (Curs, Tip) + MCP name saga_add_iesiri_valuta
  partners.py             # saga_*_partner facade: grid writes + list; UI fallback if API fails (not on preflight block)
  iesiri.py               # Facturi XML wrapper → invoices.post_on_page
  import_date.py          # Import date transport
  jurnal_banca_import.py  # I_/P_ XML → Import extrase
  efactura.py / declarations.py / validate_doc.py
  wipe.py                 # ordered delete workflow; SagaGrid.delete when the target is a catalog screen
  fx_invoice_pdf.py       # optional helper

src/markus_mcp/agent_skills/   # jobs; install via cursor_skills.py
```

`wipe.py` is a proto-generic client. Wave 0 **folds its handshake into `protocol.py` / `grid.py`**. Do not invent a second handshake.

**Ingest vs engine:** parsers and `schema.py` must be unit-testable without a browser. Adapters import `documents` + `schema`, never the reverse. Catalog JSON is the lookup; live `probe_screen` only **updates** that JSON after review.

### 4.2 `protocol.py`

```python
Outcome = Literal["success", "needs_check", "needs_choice", "warning", "error"]

class SagaResponse:
    outcome: Outcome
    raw: Any
    message: str | None
    flag_id: str | None
    validation_flags: list[dict]
    new_id: str | None

def classify(body) -> SagaResponse: ...
def request_setup(*, skip, batch_size, keyword=None, master_id=None, **extra) -> str: ...
def sender_id(page) -> str: ...
def post_with_handshake(page, url, payload, *, style, allow_choices: bool) -> SagaResponse:
    # 1) _CHECKED=false  2) Validation → true  3) Choice only if allow_choices
    # Max 3 round trips; return full chain
```

Fold in: `iesiri_valuta._post_with_validation_retry`, `_extract_created_ids`, `partners._post_clienti_row`, `wipe._delete_ex` / `_delete_classic` / `_devalidate`.

### 4.3 `grid.py`

```python
class GridModel:
    table_name, controller, primary_key
    get_data_url, create_url, edit_url, delete_url
    next_index_url, copy_detail_url, delete_master_details_url
    is_master, is_detail, master_table, selection_key
    columns: tuple[GridColumn, ...]
    write_style: Literal["classic", "ex"]
    risk: Literal["low", "medium", "high"]

class SagaGrid:
    def list(...) -> dict
    def get(pk) -> dict | None
    def next_index() -> str | None
    def create(row, *, allow_choices) -> SagaResponse
    def update(pk, row, *, allow_choices) -> SagaResponse
    def delete(pk, *, allow_choices) -> SagaResponse
    def details(master_pk, detail_table) -> dict
    def create_detail(...) -> SagaResponse
```

Rules:

- Refuse columns not in `model.columns` (`unknown_fields`).
- Never invent values; only fill `defaultValue` from the model and report it.
- Auto-`next_index` when required.
- Pre-flight `LoadDrepturiEcrane` and closed period (`GetInchidereCurenta`) before writes.
- Mutating results always include `{ok, via, endpoint, request, response_chain, screenshot_path, capture_path}`.
- `risk=high` screens: engine may read; named write tools are not registered.

### 4.4 `registry.py`

```python
SCREENS = {
  "clienti": ScreenSpec(route="Clienti", table="Clienti", pk="Cod",
                        risk="low", tools=("list","get","create","update","delete","export"),
                        named=("saga_list_partners", "saga_create_partner", ...)),
  "iesiri_valuta": ScreenSpec(..., detail_table="IesiriValutaDetalii",
                        risk="medium", named=("saga_add_iesiri_valuta",)),
}
```

Registry is how generic **reads** know a screen. Named write tools point at adapters and accept **canonical documents** (or the existing header/lines field dicts), not raw “any grid row” payloads and not file paths as the primary contract.

### 4.5 Discovery and catalog refresh

`probe_screen(page, route)` navigates, captures every `tableModel`, toolbar, report buttons, XHR dump. Used by developers (and optionally a hidden MCP tool).

1. Persist raw capture (research folder).
2. Diff against `schemas/<table>.json`.
3. If columns/endpoints changed: review, then replace the committed snapshot in the same PR as adapter/tool updates.
4. **Reads** can use a reviewed spec immediately. **Writes** still wait for one captured UI create (§6) plus an adapter if side-effects exist.

Do not auto-overwrite write catalogs from a probe in production.

### 4.6 Documents, ingest, and schema mapping

```python
# schema.py
def catalog_for(operation: str) -> Schema: ...  # header + optional detail tables
def map_fields(operation: str, user_payload: dict) -> Mapped:
    # exact names, then aliases.json, then reject unknown
    # fill only documented defaultValue from catalog

# documents/validate.py
def validate(operation: str, document: dict) -> list[str]:  # uses catalog required/types
```

Agent path for **chat**: skill loads catalog for X → agent fills those field names (or aliases) → `map_fields` → named tool preview.

Agent path for **XML**: parser produces raw tags → `map_fields` against the same catalog → same named tool.

Do **not** keep a long-term separate posting implementation per file type. Do **not** maintain a second handwritten field list in Python once the JSON catalog exists (`fx_invoice_field_catalog` / `partner_field_catalog` migrate into `schemas/`).

---

## 5. Feature → engine / named tool / skill

Legend: **E** engine+registry (reads) · **N** named write/workflow tool · **A** adapter · **R** `saga_run_report` · **S** skill · **H** human-gated · **✓** shipped.

### 5.1 Auth / session

| Feature | Plan | Notes |
|---|---|---|
| Login / OTP / firm | ✓ | keep current tools |
| Working interval | E + N | `saga_context` read; `saga_set_interval` with `confirm_write` if we automate changing it |

### 5.2 Fisiere — master data

| Feature | Plan | Notes |
|---|---|---|
| Clienti | ✓ migrate onto grid; keep tool names | adapter: Verificare / CUI |
| Furnizori | E + N + A | clone Clienti named tools (`saga_list_suppliers`, …) |
| Agenti, Grupe, Filiale, Actionari, Masini | E then N if a job needs them | do not ship 5 CRUD tools “because the menu exists” |
| Plan conturi | E + A; N read `saga_chart_of_accounts` | writes cautious |
| Gestiuni, Tipuri articole | E + A (`GetNextPK`, `LProcedure`) | named when Articole/Intrări need them |
| Articole | E + N + A | biggest nomenclator adapter |
| Salariati | H | Access=1; read-only until rights + explicit job |

### 5.3 Operatii — journals

| Feature | Plan | Notes |
|---|---|---|
| Iesiri - valuta | ✓ header/lines (format-agnostic) + migrate to grid | skill: FX PDF (and chat) |
| Iesiri (RON) | ✓ XML wrapper today → **N `saga_add_iesire(document)`** + A + Facturi XML ingest | one skill: any source |
| Intrari / Intrari valuta | N `saga_add_intrare(document)` + A; Import date remains XML *transport* | chat/PDF/XML → same document |
| Jurnal de banca | ✓ XML wrapper → **N `saga_post_bank_entries(documents)`** + ingest | skill: any source |
| Registru casa (+valuta), Deconturi | N + A | skill: cash receipt when needed |
| e-Facturi | N list/download; **H submit/cancel** | skill: review inbound |
| Imobilizari, Transferuri, Bonuri, Productie, Inventariere | E reads; N+A when a job exists | stock teardown / reglări / ops speciale = **H** |
| State salarii | H | |
| Inchidere luna | H | read status in `saga_context`; execute hard-gated |

### 5.4 Situatii — reports (23)

One `saga_run_report(name, filters)` + registry (setter, creator, `auxiliar` schema). Named wrappers only for the top jobs (balanță, jurnale, fișe, stocuri). Skill: period pack.

Declarations 406 / 205 / Intrastat = **H**. Bilant generate PDF can be R with confirm if it only files locally; ANAF submit stays H.

### 5.5 Diverse / Administrare

| Feature | Plan |
|---|---|
| Import date | ✓ `saga_import_xml` = upload transport; prefer emit from canonical when we build docs in Markus |
| Comenzi / Contracte | N+A when a job exists; `GenerareFacturi` is confirm_write + preview |
| e-Transport, REVISAL | H |
| Numere și serii | A needed by document tools |
| Config societăți / salarii, Utilizatori, Întreținere BD | H (read firm via `saga_context` is fine) |
| Despre | E read |

---

## 6. Per-screen runbook (writes)

Repeat for every new **named write** screen:

1. **Probe.** Capture `tableModel` → commit `schemas/<table>.json` (+ detail table, + aliases). Confirm table, PK, `actionsURLs`, columns.
2. **Read first.** `SagaGrid.list(batch_size=5)` vs UI. Fix the model before writing.
3. **Capture one UI create** on a throwaway `MARKUS-TEST-<timestamp>` row. Dump XHR. That is ground truth for `RowData`, `_CHECKED`, and side-effect calls.
4. **Diff** capture vs `tableColumns`. Missing keys are required or server defaults.
5. **Replay** via `page.request` + `post_with_handshake`. Verify with `getData`, not the POST body alone.
6. **Details** (documents): master → PK → lines with FK → re-read totals.
7. **Delete** the throwaway row. Record POST vs GET in the registry.
8. **Named tool** takes a **canonical document** mapped through `schema.map_fields`. Add/adjust ingest parsers in the same wave if a file format matters. Register in `server.py` **and** `tools/catalog.py` in the same commit. Adapter only if step 3 showed extra endpoints.
9. **Skill** for the job accepts **any source** (chat / XML / PDF), not one skill per extension. Do not add a skill that only wraps a single CRUD call with a hard-coded file type.
10. Never learn a protocol on real accounting data — test firm or `MARKUS-TEST-*` only.

---

## 7. Guardrails (non-negotiable)

- **Preview-then-confirm** on every mutation (`confirm_write=false` → `{requires_confirmation, preview}`; only `true` writes).
- **Never auto-answer `Choice`** unless `confirm_write=true`; always echo the question text.
- **Never invent field values.** Report auto-filled defaults.
- **No generic employee writes.**
- **Format-agnostic writes.** New named write tools take canonical documents / field dicts **after schema mapping**. File-path tools are wrappers around ingest + those tools (or Import date transport). Do not grow a second posting implementation per file type.
- **Catalog is the schema.** Do not hand-maintain a third field list in adapters. Writes use committed `schemas/*.json` until a reviewed probe updates them. Do not snapshot the entire SAGA database.
- **Human-only execute:** Inchidere lună, State salarii, Config salarii/societăți, Utilizatori, Întreținere BD, D406/205/Intrastat, e-Transport, REVISAL, Dezmembrări, Operații speciale, Reglări descărcare, e-Factura ANAF submit/cancel.
- **Rights-aware** via `LoadDrepturiEcrane`.
- **Period-aware** — refuse writes in a closed month.
- Mutating tools return endpoint, payload, response chain, screenshot, capture path.
- Single SAGA browser worker.
- `tools/catalog.py` updates in the same commit as `server.py`.
- Golden path: `data/fake_invoice_K003_FAKE_NORD_LOGISTICS.pdf` FX import + WhatsApp notify must keep working after every wave.

---

## 8. Rollout waves

Each wave: engine/registry as needed, **named tools** the agent will call, **skill** if it is a job, catalog + version bump, smoke `list_tools`, golden FX invoice.

| Wave | Engine / ingest | Named MCP | Skill | Exit |
|---|---|---|---|---|
| **0 — Foundation** | `protocol`, `discovery`, `grid`, `registry`, `context`, **`schema.py`**; seed `schemas/` from Clienti + IesiriValuta (+ wipe tables as needed); migrate Clienti + IesiriValuta + **wipe handshake** | `saga_context`, `saga_describe_screen` (from catalog), `saga_list_screens`; keep current names | none new | FX skill unchanged; `describe` matches today’s field catalogs; wipe order unchanged |
| **0b — Documents skeleton** | `documents/` + `map_fields`; lift Facturi / I_/P_ parsers | XML wrappers call parsers then mapper | — | parsers + mapper unit-tested without browser; wrappers still work |
| **1 — Generic reads** | lookups, export | `saga_list_rows`, `saga_get_row`, `saga_lookup`, `saga_export_grid` | — | list/export without new writes |
| **2 — Reports** | `reports.py` + `auxiliar` schemas | `saga_run_report` + top wrappers | period-pack | real PDF/XLS on disk |
| **3 — Master data writes** | Furnizori + Articole adapters | `saga_*_supplier`, `saga_*_item` | only if a job needs it | throwaway CRUD |
| **4 — Sales & purchases (format-agnostic)** | Iesiri / Intrari adapters | **`saga_add_iesire(document)`**, `saga_add_intrare(document)`; XML tools become thin wrappers | **one** RON sales skill: chat / PDF / XML | same posting path for chat dict and Facturi XML; totals match UI |
| **5 — Cash & bank (format-agnostic)** | RegistruCasa + bank adapters | **`saga_post_bank_entries`**, `saga_add_casa_entry`; I_/P_ wrapper thin | bank skill: chat / XML | one posting path |
| **6 — Stock / commercial** | adapters when a job exists | named document tools only | matching skill | no menu dump |
| **7 — e-Factura read** | adapter | list / download | inbound review | submit remains H |
| **8 — Gated** | read-only + hard-gated execute | explicit confirm copy | none that auto-closes a month | cannot run unattended |
| **9 — Journals leftover** | validate/devalidate; FX bank/cash/deconturi schemas; GetNrDoc; ensure-partner resolve | `saga_validate_document`; casa/bank route on Valuta | skills note abort-if-missing partner | create ≠ lock; Import extrase still for bank FX |
| **10 — Reports + H declarations + drift** | remaining Situatii provisional setters; D406/D205/Intrastat generate; catalog `diff_probe` | `saga_generate_declaration`, `saga_submit_declaration` | none that auto-file ANAF | CI fixture vs `schemas/*.json`; submit needs `TRIMITE DECLARATIE` |

Wave 0 / 0b may shuffle files without a new user-facing job. Do not start Wave 3 by copy-pasting `partners.py`. Wave 4 must not leave a permanent fork where XML posts differently from chat.

---

## 9. Testing

- **Protocol unit tests** on saved JSON (`Validation` / `Choice` / `ValidateData` / success).
- **Ingest unit tests** on fixture XML/XLS → mapped canonical documents (no browser).
- **Schema mapper tests:** aliases (`ClientNume` → `Client`), unknown keys rejected, required missing listed.
- **Catalog drift tests:** `probe` snapshot (fixture) vs committed `schemas/<table>.json`.
- **Parity test:** Facturi XML fixture and an equivalent hand-built dict produce the same mapped `RowData` before POST.
- **Live throwaway round-trip** per new named write (manual, once per wave).
- **Golden FX invoice** after every wave.
- **Skill smoke:** chat-shaped document and XML-shaped document for the same job.
- Never test on real ledgers.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| SAGA changes `RowData` keys | committed `schemas/*.json` + probe diff fails CI; review before writes |
| Copying “all of SAGA SQL” | we don’t; catalog is grid `tableModel`s for onboarded operations only |
| Stale catalog vs live SAGA | probe drift test; writes stay on committed schema until review |
| Agent invents columns not in catalog | `map_fields` rejects unknown; preview shows unmapped |
| Chat extract invents Cont / TVA | validate against catalog; preview; never invent; skill asks user |
| Agent uses a generic write on the wrong table | generic writes not on employee MCP |
| Tool API couples to XML forever | canonical documents; path tools are wrappers only |
| Two posting paths (XML vs chat) drift | one adapter; parity test in Wave 4/5 |
| `Choice` auto-answered | `confirm_write` + echo text |
| Two report calls interleave filters | single browser worker |
| `Descarca=true` returns HTML | magic-byte check |
| Access=1 looks like HTTP noise | `LoadDrepturiEcrane` first |
| Session expiry mid-skill | `IsStillConnected`; re-login only without OTP |
| Compact inventory used as backlog | this plan is source of truth |
| Wave 0 ignores `wipe.py` | handshake extracted from wipe + iesiri_valuta together |
| MCP instruction / tool list explodes | named verbs + skills; generic reads only; ingest not 77 tools |

---

## 11. Appendix — research index

Under `data/saga/research/` (tree is gitignored with `data/`; keep this index so the files are not “lost”):

- `AdvancedControls.min.js` — `parseTableModel`, getData, save, delete handshake, getNextIndex, copyDetail, `Home/ExportDate`.
- `Layout.min.js` — `LoadOperationalData`, `LoadDrepturiEcrane`, `IsStillConnected`, `Balanta/ExecutaBalanta`, `BackupDB`, `EFactura/SaveToken`.
- `modules/*.js` (~39) — per-screen business endpoints.
- `feature_inventory.json` — 77 menu items. **Do not use compact `t:` as shipped status.**
- `_menu.json`, `_pages.json`, `_modals.json`, `_common.json` — RO/EN strings for tool descriptions and `Choice` text.
- `data/saga/network-*.json` — login, partners CRUD, IesiriValuta probe/create.

Committed runtime catalog (not gitignored): `src/markus_mcp/tools/saga/schemas/*.json` — reviewed `tableModel` snapshots + `aliases.json`.

Existing Markus SAGA modules to treat as engine/ingest input, not legacy to ignore: `partners.py`, `iesiri_valuta.py` (already format-agnostic header/lines), `iesiri.py` / `jurnal_banca_import.py` (lift parsers into `documents/`), `import_date.py` (Import date transport), `wipe.py` (already knows Furnizori, Intrări/Ieșiri ± valută, `Iesiri_Incasari` allocation grids, Jurnal layers — seed schemas from these paths), `session.py`.

---

## 12. Completeness check (this revision)

The plan is **enough to execute Wave 0–0b** and to grow coverage job-by-job. It is **not** a finished spec of all 77 menu items. Use this section so implementers do not rediscover the holes.

### 12.1 In the plan and sufficient

- Layers: schema catalog, ingest, engine, named tools, skills.
- No generic employee writes; XML wrappers → document tools.
- Protocol, runbook, guardrails, waves, human-gated list.
- Seed schemas from Clienti + IesiriValuta; wipe handshake in Wave 0.

### 12.2 Decide once, then keep (were implicit)

| Topic | Decision |
|---|---|
| **Operation id** | One key per job, same in `registry.py`, `schemas/`, skills: `clienti`, `iesiri`, `iesiri_valuta`, `intrari`, `jurnal_banca`, … Not three names (`sales_invoice` vs `iesiri` vs `saga_add_iesire`). Document `kind` maps 1:1 to that id (`sales_invoice` → `iesiri` if RON, `iesiri_valuta` if FX). |
| **RON vs FX** | Skill/ingest looks at currency (and user wording). RON → `iesiri`. Non-RON → `iesiri_valuta`. Do not post FX lines on Iesiri. |
| **Batch** | Canonical tools take **one** document (or one `BankBundle`). XML wrappers loop. Chat “these 3 invoices” = three tool calls (or one wrapper that loops internally and still previews the batch). |
| **Ensure partner** | Invoice/bank jobs: search/create partner **before** posting the document (FX skill already does this). Schema for `clienti` / `furnizori` is part of those jobs, not only the invoice header. |
| **Derived vs invented** | Fetching `GetCursValutar`, `GetNrDoc` / `GetNrIesiriValutaTip` is allowed and must be labelled `auto_filled` in the preview. Guessing Cont or TVA is not. |
| **Import date vs `saga_add_intrare`** | Bulk SmartBill / NIR purchases stay **Import date** (`saga_import_xml`) until `saga_add_intrare` is proven. Chat/PDF single purchase → `saga_add_intrare` once Wave 4 exists. |
| **Furnizori ≠ Clienți** | `saga_*_partner` is Clienti. Purchases and plăți need Furnizori (`wipe.py` already has `GetData_Furnizori`). Wave 3 named supplier tools; do not reuse Clienti create for suppliers. |
| **Validare** | Creating a row ≠ locking it. Optional later named tool `saga_validate_document` (`ExecutaValidare`) with `confirm_write`. Not Wave 0. |
| **Numere și serii** | Required for Wave 4 document adapters (which series to use). Probe + schema in Wave 4, not a separate employee CRUD app. |
| **Child grids** | Wipe already deletes `Iesiri_Incasari` (receipt allocations) and bank day/entry layers. Invoice **create** does not post allocations; `saga_post_bank_entries` + Asociere does. Do not invent an allocation document until a job needs it. |
| **Scanned PDFs** | Out of scope. Skills require text-readable PDF or chat/XML. No OCR in Markus. |
| **Unlisted menu items** | Anything in the 77 not given **N** stays: probe → **E** (read) if useful; **no write tool** until there is a job. No backlog of 50 CRUD tools. |
| **Packaging** | `schemas/*.json` must be included in the PyInstaller spec / wheel (`force-include`). Frozen `--setup` still copies skills. |
| **MCP instructions** | `server.py` `instructions=` and `tools/catalog.py` update in the same commit as new tools (already said for catalog; instructions drift the same way). |
| **Tests / CI** | Add `tests/` for protocol + `map_fields` + XML fixtures (no browser). Installer workflow may stay separate; do not wait for live SAGA in CI. |
| **Shipped skills omitted from §1.5 table** | Also exists: `export-smartbill-supplier-invoices`, `import-xml-to-saga`. Keep until jobs merge. |

### 12.3 Still unknown until a live probe (do not fake)

- Whether `tableColumns` exposes a real **required** flag (U3). Until then, required = what we learned from a captured UI create + existing Python catalogs (`required_on_create` on Clienti, Cont on FX lines).
- Exact `auxiliar` per report (U6) — Wave 2.
- Report `data-api` origin (U4) — Wave 2.
- Jurnal de Bancă Import extrase is **not** a normal grid create; the wrapper stays a workflow even after `BankBundle` exists (Asociere + Accept). Canonical entries feed that workflow; they do not replace it with `grid.create` on Solduri.

### 12.4 Out of this plan

WhatsApp pairing, SmartBill Cloud login, installer/DMG, `private.data` keys — already shipped. This plan only says skills may call them and ingest may reuse SmartBill→canonical.

### 12.5 Ready / not ready

| Start now | Wait |
|---|---|
| Wave 0 engine + schema seed from Clienti, IesiriValuta, wipe targets | Wave 3+ writes without a job |
| Wave 0b parsers + `map_fields` | Treating Import date as obsolete |
| | Full 23 Situatii without `auxiliar` captures |
| | e-Factura submit, month close, payroll |

---

## 13. Master checklist — 100% SAGA automation

**Definition of 100% (this plan):** after login/OTP, an accountant can run **every onboarded job** from chat, XML, or text PDF (schema → ingest → named tool → SAGA), **every menu screen can be probed and read** if we have a reason, and **legal/destructive ops** exist only as read + hard-gated execute. **Not** in 100%: unattended ANAF submit, unattended month close, unattended payroll, OCR of scans, cloning 77 CRUD tools with no job.

Tick `[x]` only when the exit next to the item is true. `[H]` = execute stays human-gated even when the line is otherwise done.

Per-screen write items follow the runbook in §6 (probe → read → capture create → catalog → replay → named tool → skill if it is a job).

### 13.1 Foundation (Wave 0)

- [x] `protocol.py` — classify + `_CHECKED` / `uvf` handshake; POST-then-GET delete; `SenderID`; unified `RequestSetup`
- [x] Handshake folded from `iesiri_valuta`, `partners`, **and** `wipe` (no second protocol)
- [x] `grid.py` — list / get / create / update / delete / details
- [x] `discovery.py` — `probe_screen` → raw `tableModel`
- [x] `registry.py` — operation ids (`clienti`, `iesiri`, `iesiri_valuta`, …)
- [x] `schema.py` + `map_fields` + `aliases.json`
- [x] `context.py` — `LoadOperationalData`, rights, interval, closed-period check
- [x] `saga_context`, `saga_list_screens`, `saga_describe_screen` MCP tools
- [x] Clienti + IesiriValuta **migrated** onto grid/schema with **zero tool-name changes** (Clienti UI fallback remains for non-preflight API failures; `partners.py` is the MCP facade, not a second grid client)
- [x] Wipe still deletes in the same order; catalog screens use `SagaGrid.delete`, Solduri / Iesiri_Incasari keep wipe-owned URLs
- [x] `schemas/*.json` in wheel + PyInstaller spec
- [x] `server.py` instructions + `tools/catalog.py` updated in the same commits
- [ ] Golden FX PDF skill still works end-to-end (incl. WhatsApp `Eu`)

### 13.2 Ingest (Wave 0b)

- [x] `documents/` types as facades over catalog tables
- [x] Lift Facturi XML parser; `saga_import_iesiri_xml` = parse → map → (later) `saga_add_iesire`
- [x] Lift I_/P_ XML parser; `saga_import_incasari_xml` = parse → map → bank workflow
- [x] Unit tests: parsers + aliases + unknown keys + missing required (no browser)
- [x] Optional MCP: `saga_parse_facturi_xml` / `saga_parse_incasari_xml` (or parse only inside write preview)

### 13.3 Generic reads (Wave 1)

- [x] `saga_list_rows` / `saga_get_row` / `saga_lookup` / `saga_export_grid`
- [x] Lookups follow `selectModel` + Home redirects
- [x] Export via `Home/ExportDate`; file is real xlsx (magic-byte check; live firm export not yet golden)

### 13.4 Reports (Wave 2)

Engine:

- [x] `reports.py` — SetDataRaport → CreateRaport; magic-byte check; `data-api` from the page
- [x] `saga_run_report(name, filters)` + `auxiliar` schemas in catalog
- [x] Period-pack skill (balanță + jurnale + fișe for the working interval)
- [x] `saga_context` refuses or warns on closed period where relevant

Per Situatii feature (schema `auxiliar` + at least one successful PDF/XLS on a test firm).
Provisional setters exist in `reports.json` for the remaining names; **do not tick** until a real test-firm file is saved:

- [ ] Fise conturi
- [ ] Balante
- [ ] Carte mare
- [ ] Jurnale de cumparari / vânzari
- [ ] Situatie furnizori
- [ ] Situatie clienti
- [ ] Situatie cecuri / bilete la ordin
- [ ] Registru jurnal
- [ ] Registru inventar
- [ ] Bilant — **local PDF only**; ANAF submit is `[H]` in §13.8
- [ ] Fise articole
- [ ] Situatie aprovizionari
- [ ] Situatie vânzari
- [ ] Situatie consumuri
- [ ] Situatie obiecte inventar
- [ ] Situatie productie
- [ ] Situatie stocuri
- [ ] Situatie ambalaje SGR
- [ ] Raport de gestiune
- [ ] Situatii manageriale
- [ ] Situatie comenzi (Diverse, report)

### 13.5 Auth / session (4)

- [x] Login (`saga_login`)
- [x] OTP / browser authorize (`saga_submit_otp`; user clicks email)
- [x] Firm select (inside login)
- [x] Working interval — read in `saga_context`; [x] `saga_set_interval` with `confirm_write`

### 13.6 Fisiere — master data (12)

Each line: schema catalog · generic read · named write (if a job) · aliases.

Honesty: `[x]` below means a named job or a **probed/used** catalog. Wave 6–9 screens whose JSON says “best-effort until a live tableModel probe” stay `[ ]` — `saga_list_rows` may 404. That is not “readable”.

- [x] **Clienti** — named tools; writes + list/search via `SagaGrid`; UI fallback only if the API fails (not on closed-month / rights preflight); [x] `map_fields`
- [x] **Furnizori** — schema (wipe endpoints, not a live probe); E; N `saga_*_supplier`; not Clienti
- [x] **Articole** — schema; E; N `saga_*_item`; TVA/preturi/SGR/barcode side-effect endpoints are **not** auto-called (pass those fields if the user specified them)
- [x] **Plan conturi** — schema; E `saga_chart_of_accounts`; writes only if a job needs them
- [x] **Gestiuni** — schema; E via `saga_list_rows` / `saga_lookup`; named write not added (no job yet)
- [x] **Tipuri de articole / servicii** — schema; E via generic reads; named write not added (no job yet)
- [ ] **Agenti** — schema stub (unprobed); `saga_list_rows` may 404; N only if a job needs it
- [ ] **Grupe** — schema stub (unprobed)
- [ ] **Filiale** — schema stub (unprobed)
- [ ] **Actionari** — schema stub (unprobed)
- [ ] **Masini** — schema stub (unprobed)
- [H] **Salariati** — schema stub (unprobed); **no unattended write**

### 13.7 Operatii — journals (24)

**Sales / purchases (Wave 4)** — format-agnostic: chat / XML / text PDF → same adapter.

- [x] **Iesiri - valuta** — `saga_add_iesiri_valuta` is a thin name over `invoices._add` / `post_on_page` (same path as `saga_add_iesire` when Valuta is not RON); FX extras (Curs/Tip) stay in `iesiri_valuta.py`; skill = any source
- [x] **Iesiri** — XML wrapper shipped; [x] schema; [x] `saga_add_iesire(document)`; [x] XML wrapper = thin loop over `post_on_page`; [x] one RON sales skill (chat/PDF/XML); [ ] totals match UI (live); [x] RON vs FX routing
- [x] **Intrari** — schema; `saga_add_intrare(document)`; chat/PDF skill; bulk NIR stays Import date
- [x] **Intrari - valuta** — schema; same `saga_add_intrare` when Valuta is not RON; `GetCursValutar` fills Curs when omitted
- [ ] **Numere și serii** (Administrare) — schema stub (unprobed); adapters still pick `GetNrDoc` / `GetNrIesiriValutaTip` when `NrDoc` omitted (`auto_filled`)
- [x] **Validare / devalidare** — `saga_validate_document` with `confirm_write` (not implied by create)
- [x] Ensure partner: Clienți before Ieșiri; Furnizori before Intrări (skills create first; adapter resolves and aborts if missing — does not auto-create)

**Bank / cash (Wave 5)**

- [x] **Jurnal de banca** — I_/P_ XML + Asociere shipped; [x] schema + `BankBundle` parse; [x] `saga_post_bank_entries`; [x] XML convenience wrapper still `saga_import_incasari_xml` (same Import extrase worker); [x] skill chat/XML; [x] still Import extrase workflow (not `grid.create` on Solduri)
- [x] **Jurnal de banca - valuta** — schema + same Import extrase workflow when Moneda is not RON
- [x] **Registru de casa** — schema; `saga_add_casa_entry`; [ ] chitanță PDF if a job needs it
- [x] **Registru de casa - valuta** — same `saga_add_casa_entry` + `GetLastValuta` when Curs omitted
- [ ] **Deconturi** — schema stub (unprobed)
- [ ] **Deconturi - valuta** — schema stub (unprobed)
- [ ] **Cecuri, BO emise/primite** — schema stub (unprobed)

**e-Factura (Wave 7)**

- [x] **e-Facturi** list / download inbound; skill: review (`saga_efactura_list` / `download`). WEB may still be issued-send-only for some firms.
- [H] e-Factura ANAF **submit / cancel / token** — `saga_efactura_submit` / `cancel` exist; never unattended (`confirm_phrase`)

**Stock / production (Wave 6) — N+A only when there is a job; otherwise E after a live probe. `[ ]` = schema stub, not proven readable.**

- [ ] **Articole contabile** — schema stub (unprobed)
- [ ] **Imobilizari** — schema stub (unprobed)
- [ ] **Transferuri** — schema stub (unprobed)
- [ ] **Bonuri de consum** — schema stub (unprobed)
- [ ] **Dare în folosinta ob. inv. (BonuriOI)** — schema stub (unprobed)
- [ ] **Productie** — schema stub (unprobed)
- [ ] **Inventariere** — schema stub (unprobed)
- [H] **Dezmembrari** — schema stub (unprobed); no unattended write
- [H] **Operatii speciale** — schema stub (unprobed); no unattended write
- [H] **Reglari descarcare** — schema stub (unprobed); no unattended write

**Always human execute (Wave 8)**

- [H] **State salarii** — schema stub (unprobed); D112/filings `[H]`
- [H] **Inchidere luna** — status in `saga_context`; execute `saga_close_month` `[H]` with `confirm_phrase='INCHIDE LUNA'`

### 13.8 Situatii — declarations (subset of 23; rest in §13.4)

- [H] Declaratia 406 (SAF-T) — generate/read `saga_generate_declaration`; submit `saga_submit_declaration` `[H]` (`TRIMITE DECLARATIE`)
- [H] Declaratia 205 — same
- [H] Declaratia Intrastat — same

### 13.9 Diverse (8)

- [x] **Import date** — `saga_import_xml`; [x] emit Facturi XML from canonical (`emit_facturi_xml`)
- [ ] **Comenzi** — schema stub (unprobed)
- [ ] **Contracte** — schema stub (unprobed); `GenerareFacturi` stays `confirm_write` when a named tool exists
- [ ] **Cheltuieli / venituri în avans** — schema stub (unprobed)
- [ ] **Diurne** — schema stub (unprobed)
- [x] **Situatie comenzi** — covered under reports (§13.4; provisional setter)
- [H] **e-Transport** — `[H]` via `saga_submit_declaration` (`TRIMITE DECLARATIE`)
- [H] **REVISAL** — `[H]` via `saga_submit_declaration` (`TRIMITE DECLARATIE`)

### 13.10 Administrare (6)

- [x] **Despre...** — E (`saga_about`)
- [x] **Configurare societati** — read via `saga_context` / LoadOperationalData; **write `[H]`**
- [H] **Configurare salarii** — `[H]`
- [ ] **Numere si serii** — schema stub (unprobed); see §13.7
- [H] **Utilizatori** — `[H]`
- [H] **Intretinere BD** — `[H]`

### 13.11 Jobs / skills (accountant-facing)

Shipped (keep until merged into “any source” skills):

- [x] `import-fx-invoice-to-saga`
- [x] `smartbill-to-saga-import`
- [x] `export-smartbill-supplier-invoices`
- [x] `import-xml-to-saga`
- [x] `import-iesiri-xml-to-saga`
- [x] `import-incasari-xml-to-saga`
- [x] `wipe-saga-data`

To add (one skill per job, any input format):

- [x] Sales invoice **any source** (RON) — chat / PDF / Facturi XML → `saga_add_iesire`
- [x] FX invoice **any source** — retarget existing FX skill to catalog/`map_fields`
- [x] Purchase invoice **any source** — chat/PDF → `saga_add_intrare`; bulk NIR → Import date
- [x] Bank entries **any source** — chat / I_/P_ XML → `saga_post_bank_entries`
- [x] Cash receipt — `saga_add_casa_entry`
- [x] Period pack — `saga_run_report` + `saga_context`
- [x] Inbound e-Factura review (no auto-submit)
- [x] Ensure-partner baked into invoice/bank skills (Clienți / Furnizori)

### 13.12 Tests, CI, packaging

- [x] `tests/` protocol fixtures (Validation / Choice / ValidateData / success)
- [x] `tests/` `map_fields` + XML fixtures
- [x] Parity: XML fixture vs hand-built dict → same mapped header/lines (not a live RowData POST)
- [x] Catalog drift test (probe fixture vs `schemas/*.json`)
- [x] No live SAGA in CI
- [x] Installer still ships schemas + skills

### 13.13 Done when

- [ ] All items in §13.1–13.2 and §13.12 are `[x]`
- [ ] Every feature in §13.5–13.10 is either `[x]` (automated job or read) or `[H]` with a gated tool/read — **no silent gaps**
- [ ] §13.4 reports that accountants actually use have at least one golden PDF on the test firm
- [x] §13.11 “any source” skills exist for sales, purchases, bank (the daily work)
- [ ] Remaining stock/commercial/nomenclator rows have an **E schema stub** (catalog + `saga_list_rows` wiring). Not live-proven; list may 404 until a probe. Unticked in §13.6–13.10 until a reviewed `tableModel` lands.

That last bullet is how 77/77 is closed without 77 write tools. E stubs are not a substitute for a reviewed probe.
