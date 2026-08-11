# SAGA WEB → Markus MCP: full tool coverage plan

Goal: expose **every SAGA WEB feature listed in `data/saga/research/feature_inventory.json` (77 features)** as Markus MCP tools, by reverse-engineering what the SAGA WEB UI posts and replaying the same URLs with Playwright's `page.request` inside the already-authenticated persistent browser session.

This document is the single source of truth for that work. It contains the protocol reference, the unknowns and how to capture them, the code architecture, the complete feature→tool mapping, the per-screen runbook, guardrails, and the rollout waves.

---

## 0. Executive summary

SAGA WEB is an ASP.NET MVC app whose entire data layer is a **single generic grid component** (`AdvancedControls.min.js`, ~1 MB, `AdvancedTable`). Every nomenclator, journal and document screen — `Clienti`, `Furnizori`, `Articole`, `Intrari`, `Iesiri`, `IesiriValuta`, `RegistruCasa`, `Imobilizari`, `Comenzi`, `StateSalarii`, … — is an instance of that same component driven by a JSON **`tableModel`** rendered into the page.

That means we do **not** need 77 bespoke integrations. We need:

1. **One generic grid client** that speaks the AdvancedControls protocol (read / create / edit / delete / next-index / master-detail / export).
2. **One discovery layer** that reads `tableModel` off any rendered SAGA screen and derives endpoints + column schema automatically.
3. **One report client** for the `Rapoarte/*` two-step PDF/XLS pipeline (covers all 23 "Situatii" report features at once).
4. **Thin per-screen adapters** only where a screen has extra business endpoints (FX rate lookup, `LProcedure`, `ExecutaValidare`, `GetNrDoc`, e-Factura, …).

Everything already shipped (`Clienti` CRUD, `IesiriValuta` header+lines) is a hand-written special case of this generic layer. **Wave 0 of this plan is to extract that generic layer out of `partners.py` / `iesiri_valuta.py`**, then the remaining 70+ features become configuration plus a handful of adapters.

---

## 1. Protocol reference (reverse-engineered)

Everything in this section is confirmed from `data/saga/research/AdvancedControls.min.js`, `Layout.min.js`, and `data/saga/research/modules/*.js`, plus the live captures in `data/saga/network-*.json`.

### 1.1 Session and transport

| Concern | Value |
|---|---|
| Login origin | `https://web.sagasoft.ro` (`SAGA_BASE_URL`) |
| App origin after firm connect | `https://web2.sagasoft.ro/sagac` (`SAGA_APP_BASE_URL`) |
| Report/API origin | read at runtime from `document.body.dataset.api` (`$("body").data("api")`) — **do not hardcode** |
| Auth | persistent Chromium profile in `./data/saga-session`; cookies carry the session |
| Required headers | `X-Requested-With: XMLHttpRequest`, plus `X-SAGA-Valid-Token: <cookie SAGA-Valid-Token-JS>` |
| Existing helper | `saga_session._auth_headers(page)` already does this |
| All calls go through | `page.request.get/post/fetch` on the logged-in page — cookies are shared automatically |

Session/context endpoints worth wrapping as tools:

- `GET Home/LoadOperationalData` → toolbar state, current firm (`Toolbar.CodFirma`), current user, `Societ`, `Configurare`, `TipContabilitate` (SC/PS/ONG/IFN), `FaraStocuri`, working interval. **This is the "who am I / what firm / what period" call.**
- `GET Home/LoadDrepturiEcrane`, `Home/GetDreptEcran`, `Home/GetDreptCont` → per-screen rights (drives "can this user do X?").
- `GET Home/IsStillConnected` → session liveness, cheaper than a screenshot.
- `GET Home/GetTipContabilitate`, `Home/GetCurrentUser`, `Home/GetDatabaseSize`, `Home/CheckDBStatus`.

### 1.2 The `tableModel` — the key to generic coverage

`AdvancedControls.parseTableModel()` parses a JSON blob per grid instance:

```js
let auxModel = JSON.parse(tableModel);
tableName        = auxModel.tableName;          // e.g. "Clienti", "IesiriValutaDetalii"
controllerName   = auxModel.controllerName;     // e.g. "Clienti", "IesiriValuta"
primaryKey       = auxModel.primaryKey;          // e.g. "Cod", "ID_Iesire"
masterTableName  = auxModel.detailSetup.masterTableName;
isMaster         = auxModel.detailSetup.isMaster;
isDetail         = auxModel.detailSetup.isDetail;
selectionKey     = auxModel.detailSetup.selectionKey;
actionsURLs = {
    getData:            auxModel.tableConfig.actionsURLs.getData,
    create:             auxModel.tableConfig.actionsURLs.create,
    edit:               auxModel.tableConfig.actionsURLs.edit,
    delete:             auxModel.tableConfig.actionsURLs.delete,
    getNextIndex:       auxModel.tableConfig.actionsURLs.getNextIndex,
    copyDetail:         auxModel.tableConfig.actionsURLs.copyDetail,
    deleteMasterDetails: auxModel.tableConfig.actionsURLs.deleteMasterDetails,
};
tableColumns = auxModel.tableColumns;  // name, inputType, selectModel, defaultValue, …
```

Consequences:

- **We never have to guess an endpoint.** Open the screen, read `tableModel`, and you have the exact create/edit/delete/getData URLs SAGA itself uses.
- **We never have to guess a column list.** `tableColumns[i].name` is the exact `RowData` key; `inputType` tells us Input / Select / Checkbox / Hidden / Lock; `selectModel` names the combo (see §1.7); `defaultValue` gives SAGA's own default.
- DOM conventions that let us enumerate grids on a page without any JS internals:
  - container: `#containerAdvancedTable_<TableName>`
  - grid: `#tableMain_<TableName>`, toolbar `#toolbar_<TableName>`
  - per-cell inputs: `.rowFieldInput_<ColumnName>`, display cells `.rowFieldText_<ColumnName>`
  - toolbar buttons: `.buttonOperationAdd_<TableName>`, `…Edit…`, `…Save…`, `…Cancel…`, `…Delete…`, `.buttonOperationExportExcel_<TableName>`
- Global JS helpers available via `page.evaluate`: `getTable("<TableName>")` returns the live table API (`GetVirtualData`, `GetDataByPK`, `GetRequestSetup`, `SelectRowByIndex`, `ToolbarActionAdd/Edit/Save/Delete`, `RefreshRow`, `SyncToSelectedData`, …). `tabID` is the `SenderID`.

### 1.3 Read protocol (`getData`)

```js
$.ajax({ type:'GET', url: actionsURLs.getData,
         data: { RequestSetup: JSON.stringify(requestSetup.json) } })
// → { data: [...rows...], pageCount: n }
```

`RequestSetup` is a `DataRequestSetup(id, page, filter, sortMode, sortColumn)` serialized via its `.json` property. Confirmed / observed keys:

| Key | Meaning |
|---|---|
| `Skip`, `BatchSize` | paging (confirmed working today in `partners.py`) |
| `GetRowsCount` | ask for total count |
| `FilterKeyword` | free-text search string |
| `FilterColumns` | array of column names to search (defaults to all non-Lock/non-Hidden) |
| `FilterSearchType` | 0 = starts-with, 1 = contains, 2 = exact (from the three radio options) |
| `FilterCaseSensitive` | bool |
| `FilterCurrentTable` | bool |
| `SortColumn`, `SortMode` | sorting |
| `auxiliar` | JSON string of screen-specific filters — **this is what reports consume** (see §1.9) |
| ctor arg `id` | fetch a single row by PK (used by `refreshRow`) |

> The exact full shape of `DataRequestSetup.json` is the one remaining unknown — see §2.1 for the one-line capture that resolves it.

### 1.4 Write protocol (`create` / `edit`) — the `RowData` + `_CHECKED` handshake

Two request families exist; both are already implemented somewhere in our codebase.

**(a) Classic AdvancedControls (used by every document/detail grid, e.g. `IesiriValuta`):**

```
POST <actionsURLs.create | actionsURLs.edit>
  RowData  = JSON.stringify(rowObject)     # keys are tableColumns[].name
  _CHECKED = "false"                        # first pass = validation pass
  SenderID = tabID
  IsPaste  = "false"
  uvf      = ""                             # or JSON array of user validation flags
```

Response types:

| `type` | Meaning | Our action |
|---|---|---|
| `Validation` | server asks to re-post confirmed | re-POST identical body with `_CHECKED="true"` |
| `Choice` | modal question (`status` text, `flagId`) | re-POST with `uvf` = `[{id: flagId, userChoice: "Yes"}]` — **only when the tool was called with `confirm_write=true`** |
| `Warning` | blocking message in `status` | surface to user, do not retry |
| *(none / success)* | saved | extract new PK |

A third variant posts a single `crudRequest` object with `UserValidationFlags` and `CRUDOperation: "Create" | "Update"`.

**(b) "Ex" style (used by `Clienti`):**

```
POST Clienti/Create_Clienti | Clienti/Edit_Clienti
  Data[<Column>] = <value>   (one form field per column)
  _CHECKED = "false"
  IsPaste  = "false"
  uvf      = JSON  # [{"id": "...", "userChoice": "Yes"}]
# → { success: true } | { errorCode: "ValidateData", validationFlags: [...] }
```

The generic client must **try the family implied by the screen and fall back to the other**, because SAGA is inconsistent across controllers. Both are already proven in `partners.py` (`_post_clienti_row`) and `iesiri_valuta.py` (`_post_rowdata` / `_post_with_validation_retry`) — the fallback logic gets unified in Wave 0.

### 1.5 Delete protocol

```js
let parameters = { Id: <pk>, _CHECKED: 'false', SenderID: tabID };
$.ajax({ url: actionsURLs.delete, dataType:'json', data: parameters })  // NOTE: jQuery default = GET
// type == "Validation" → repeat with _CHECKED:'true'
// type == "Choice"     → answer via flagId, may add parameters["Type"] = result.flagId
```

Notes:
- The UI issues this as **GET with query params** (jQuery's default). Our current `partners.py` uses POST and works for `Clienti` — keep POST-then-GET fallback in the generic client.
- Master rows with details also expose `actionsURLs.deleteMasterDetails`.
- After deleting a detail row of `IntrariDetalii` / `IesiriDetalii` / `IntrariValutaDetalii` / `IesiriValutaDetalii`, the UI calls `GetTableMaster().RefreshRow()` — our tools should re-read the master row to return fresh totals.

### 1.6 PK generation, copy, master–detail

- `GET actionsURLs.getNextIndex` (no params) → next PK. Called automatically unless `tableConfig.avoidPKGeneration`, and **always** for `Intrari`, `Iesiri`, `IntrariValuta`, `IesiriValuta`.
- Screen-specific variants seen in module JS: `Gestiuni/GetNextPK`, `Actionari/GetNextCod`, `Filiale/GetCod`, `Imobilizari/GetNrInventar`, `Inventariere/GetNrDoc`, `Transferuri/GetNrDoc`, `Productie/GetNrDoc`, `Contracte/GetNrContracte`.
- `actionsURLs.copyDetail` with `{ originId, targetId, negative }` duplicates detail lines — this is how "copy a document" works.
- Master→detail: the detail grid's `getData` is called with the master PK as the `DataRequestSetup` `id`/selection argument (`detailSetup.selectionKey` names the FK column). Document tools therefore always run: create master → read back PK → create each detail row with the FK set.

### 1.7 Lookups / combo boxes

- Data: `GET <ControllerName>/GetData_ComboBox_<comboName>` where `<ControllerName>` is the **owner table's** controller. Documented redirects to `Home` exist for: `BugCategorie*`, `ContTipuriArticol*` → `Home/GetData_ComboBox_ContGeneral`, `Import_Gestiune`, `Proiect_*` → `Home/GetData_ComboBox_Proiect`, `ContCredit_TipuriContracte` / `ContPenalizari_TipuriContracte` → `Home/GetData_ComboBox_ContTipuriCont…`, and `Balanta` combos force controller `Balanta`.
- Markup: `GET Home/GetAdvancedComboBoxViewComponent?Type=<selectModel>&OwnerTableName=<tableName>` returns the dropdown HTML. Useful only for UI fallback; for MCP we want the data endpoint.
- The combo name for a column is `tableColumns[i].selectModel`. So **`saga_lookup(table, column)` is fully derivable** — no per-screen work.

### 1.8 Screen-specific business endpoints (the "adapter" layer)

These are the calls a screen fires *around* the CRUD, and they are what makes a document post correctly. Full inventory extracted from `modules/*.js`:

| Concern | Endpoints |
|---|---|
| Partner validation / defaults | `Clienti/Verificare`, `Clienti/VerificareAll`, `Clienti/LProcedure_Clienti`, `Furnizori/Verificare`, `Furnizori/VerificareAll`, `Furnizori/LProcedure_Furnizori`, `Home/CheckCF`, `Home/GetBanca` |
| Chart of accounts | `PlanConturi/LProcedure`, `PlanConturi/GetTipSintetic`, `PlanConturi/VerifAnalitic121`, `PlanConturi/ActualizarePlanConturi`, `Home/GetDreptCont` |
| Items / pricing / VAT | `Articole/GetTVAArticol`, `Articole/GetDataArticoleTVA`, `Articole/ExecutaSchimbareTVA`, `Articole/IsVandabil`, `Articole/CheckSGR`, `Articole/AnteEdit`, `Articole/GenereazaCB`, `Articole/GetBrut`/`SetBrut`, `Articole/UpdateGarantie`, `Articole/ActualizeazaPreturiArticol`, `PreturiVanzare/*`, `Home/GetDataArticol`, `Home/GetTVA`, `Home/GetDataArticolCodBare` |
| FX | `IntrariValuta/GetCursValutar` (already used by our FX invoice tool) |
| Cash / bank | `RegistruCasa/SetActFact`, `GetClientByContAnalitic`, `GetFurnizorByContAnalitic`, `SetContCasa`, `GetAnaliticByCod`, `SetContDifCurs`, `GetLastValuta`, `SetFiltruOP`, `GetDefaultCont`, `GetDefaultAnalitic`, `SetDataSold`, `GetConturi` |
| Document lock (validare) | `<Controller>/ExecutaValidare` + `ExecutaDevalidare` for `Intrari`, `Iesiri`, `IesiriValuta`, `Bonuri`, `BonuriOI`, `Transferuri`, `Productie` (+`…Master`), `Imobilizari`, `Inventariere`, `StateSalarii`, and the many `InchidereLuna/ExecutaValidare_*` |
| Accounting note side-effect | `Home/ExecutaInsMMod` (fires after saving journal docs — the `executaInsMMod("S")` call in AdvancedControls) |
| Contracts | `Contracte/GenerareFacturi`, `SaveData_GenerareFacturiContracte`, `CheckRate`, `CheckValuta`, `ModificareCurs`, `GetNrContracte`, `CorectezTVA` |
| e-Factura | `EFactura/ReadToken`, `SaveToken`, `ImportEFactura`, `LoadFacturiImport`, `LoadIstoricEFacturiImport`, `AnulareEFactura`, `GetFacturiGenerateDarNetransmise`, `GetFacturiCuEroriLaTransmitere`, `SalveazaDate_EFactGenerareSiTransmitere`, `SalvareSetare`, `LoadSetariGenerale`, `ExistaFisiereArhivaEFactura`, `Home/GetViewDownloadEFacturi`, `Home/GetViewCodAccesSPV` |
| Import | `ImportDate/UploadXMLFiles`, `ImportFactura`, `AnuleazaImportXML`, `StergeFiserXML` |
| Balance / closing | `Balanta/ExecutaBalanta`, `InchidereLuna/*` (~74 endpoints), `Bilant/*` (~23 endpoints incl. `ActualizareDate`, `ActualizareFormule`, `ValidareData`, `GenerarePDF_Bilant`) |
| DB admin | `BackupDB/*`, `Home/UpdateDB` |

### 1.9 Report protocol (covers all "Situatii" features)

Confirmed pattern (from `IesiriValuta.js`, identical shape across modules):

```js
// step 1 — push filters into server session
t = getTable("IesiriValuta").GetRequestSetup();
t.auxiliar = JSON.stringify(screenFilters);
await $.ajax({ type:"Post", url:"Rapoarte/SetDataRaportListaIesiri",
               data:{ Filtru: t.auxiliar, Titlu: "<report title>",
                      Tip: "Export", SortColumn: i, SortMode: r } });

// step 2 — fetch the rendered report
src = $("body").data("api") + "/Rapoarte/CreateRaportListaIesiri?Filtru=Export&Descarca=true"
```

So every report is: **POST `Rapoarte/SetDataRaport<X>` (or `SetDateRaport<X>` / `SetDetaliiRaport<X>`) → GET `<apiBase>/Rapoarte/CreateRaport<X>PDF?Filtru=Export&Descarca=true`**, and we save `response.body()` to `./data/saga/reports/<name>.pdf`. `Descarca=false` renders inline; `Descarca=true` downloads.

Extracted report inventory (44 setters, ~100 `CreateRaport*` endpoints) — enough to build every report tool without further discovery. Highlights:

- Setters: `Balanta`, `Bilant`, `Intrari`, `ListaIesiri`, `Articole`, `Imobilizari`, `ImobilizariRegistru`, `Casa`, `OP`, `Deconturi`, `Inventariere`, `Productie`, `Consumuri`, `Contracte`, `Chitanta`, `AnexaComanda`, `AnexaCB`, `Etichete`, `Garantie`, `Masini`, `Oferta`, `Reteta`, `NT`, `Creditare`, `DI`, `Monetar`, `Deseuri`, `Bonuri`, `Profit`, `InchidereAn`, `InchidereDetaliataAn`, `InchidereAnRegistru`, `SitLunare`, `TransferuriNIR`, `Pontaj`, `Card`, `StateSalarii`, `SituatiiSal`, `SimulareSal`, `AdeverinteSalarii`, `Concedii`, `ListaConcedii`, `CentralizareConcedii`, `ProgramareCO`, `Tichete`.
- Creators: `BalantaPDF`, `IntrariPDF`, `IntrariNCPDF`, `FacturaIntervalPDF`, `FacturaPDFNoDownload`, `ListaIesiri`, `ArticolePDF`, `ProductiePDF`, `InventarierePDF`, `TransferuriPDF`/`TransferuriNIRPDF`, `RegistruCasaPDF`/`ValutaPDF`/`TotalPDF`/`ChitantaPDF`/`NTPDF`/`CreditarePDF`/`DPPDF`/`DIPDF`/`MonetarPDF`, `JurnalBancaPDF`/`ValutaPDF`/`TotalPDF`/`BorderouPDF`, `JurnalDeconturiPDF`/`ValutaPDF`, `DecontCheltuieliPDF`, `ImobilizariFisaPDF`/`ReceptiePDF`/`CasarePDF`/`PlanAmortPDF`/`RegistruPDF`, `SituatiiLunarePDF`, `SituatieMarfuri`, `StocBCPDF`, `OIPDF`, `ConsumuriPDF`, `ComandaIesirePDF`/`ComandaIntrarePDF`/`ComandaConsumuriPDF`, `ContractePDF`, `OfertaPDF`, `GarantiePDF`, `EtichetePDF`, `OPPDF`, `ProfitPDF`, `InchidereAnPDF`, `Bilant*PDF` + `BilantNota1..10PDF`, `BilantDeclaratiePDF`, all `StateSalarii*PDF` / `Sal*PDF` / `AdeverinteSalariatiPDF`, `FoaieParcursPDF`, `OrdinDeDeplasarePDF`, `SituatieCosturiMasiniPDF`, `SalConcediiCentralizareXLS`.
- Direct PDF generators (bypass the two-step): `Bilant/GenerarePDF_Bilant`, `Bilant/GenerarePDF_Extra`, `InchidereLuna/GenerarePDFDeclaratie`, `Salariati/GenerarePDF_Adeverinte`, `StateSalarii/GenerarePDF_ConcediiOdihna`, `StateSalarii/GenerarePDF_D112`, `Actionari/ExecutaGenerarePDF`.
- Print-option views (skippable for MCP; we set params directly): `Home/GetViewTiparire*`.
- Signature combos: `Rapoarte/GetLastData_ComboBox_Semnaturi`.

### 1.10 Excel export protocol

```
POST Home/ExportDate
  TableName, RequestSetup, Tip, RowsExport, ConfigRowsExport,
  ExcludedIDs, DetailsSetup, ConfigRowsDetailsExport, ExportToate
```
Support endpoints: `Home/GetViewDataExport`, `Home/GetExportColumnPreferences`, `Home/SaveExportColumnPreferences`, `Home/GetCustomColumnSizes`. This gives us **"export any grid to Excel"** as a single generic tool for all 40+ grids.

---

## 2. Unknowns to capture live (must-do before Wave 1)

Small, bounded list. Each has an exact capture recipe. Ship a temporary `saga_probe_screen` tool (§3.4) and run it once per screen; store output under `data/saga/research/tablemodels/<Screen>.json`.

### 2.1 `DataRequestSetup.json` exact shape
```python
page.evaluate("() => JSON.stringify(new DataRequestSetup().json)")
page.evaluate("(t) => JSON.stringify(getTable(t).GetRequestSetup())", "Clienti")
```
Result pins down paging/sorting/filter keys and the `auxiliar` slot. Blocks: generic list/search + reports.

### 2.2 `tableModel` per screen
Not in a global; it is the constructor argument. Two ways, in order:
```python
# a) intercept the model at parse time (inject before navigation)
page.add_init_script("window.__sagaModels=[];const P=JSON.parse;JSON.parse=function(s){const r=P.apply(this,arguments);if(r&&r.tableName&&r.tableConfig&&r.tableConfig.actionsURLs){window.__sagaModels.push(r);}return r;};")
# b) fall back to scraping DOM conventions
page.eval_on_selector_all("[id^='containerAdvancedTable_']", "els => els.map(e => e.id.replace('containerAdvancedTable_',''))")
```
Blocks: everything generic. **Highest priority.**

### 2.3 `tableColumns` entry shape
Known keys from usage: `name`, `inputType` (contains `Input` / `Select` / `Checkbox` / `Hidden` / `Lock`), `selectModel`, `defaultValue`. Dump one real array to learn the rest (required flags, max length, numeric scale, caption).

### 2.4 Report API base
```python
page.get_attribute("body", "data-api")
```

### 2.5 `SenderID` / `tabID`
```python
page.evaluate("() => (typeof tabID!=='undefined'&&tabID!=null)?String(tabID):'0'")
```
Already implemented in `partners.py`; move to shared.

### 2.6 Per-screen `auxiliar` filter shape
Each report screen builds its own filter object from its modal. Capture by opening the print modal once with network capture on, or read the `u.<Field>=…` assignments in the module JS (they are readable even minified, e.g. `u.Neachitate`, `u.Tip`, `u.TVAI`, `u.Tert`, `u.Agent` for `ListaIesiri`).

### 2.7 Rights matrix
`GET Home/LoadDrepturiEcrane` once → which screens this user may touch. `feature_inventory.json` already flags `access: "1"` (restricted) for `Salariati`, `State salarii`, `Configurare salarii`.

---

## 3. Architecture

### 3.1 Target file layout

```
src/markus_mcp/tools/saga/
  session.py            # exists — auth, browser thread, capture, api_request
  credentials.py        # exists
  protocol.py           # NEW — response classification + validation handshake
  discovery.py          # NEW — tableModel/tableColumns extraction + cache
  grid.py               # NEW — generic AdvancedControls client (read/create/edit/delete/next/detail)
  registry.py           # NEW — screen registry: feature → route/controller/table/PK/flags
  reports.py            # NEW — Rapoarte two-step client + report registry
  exports.py            # NEW — Home/ExportDate client
  lookups.py            # NEW — GetData_ComboBox_* client with Home redirects
  context.py            # NEW — LoadOperationalData / rights / interval
  adapters/             # NEW — thin per-screen business logic
    __init__.py
    clienti.py          # migrate from partners.py
    furnizori.py
    articole.py
    intrari.py
    iesiri.py
    iesiri_valuta.py    # migrate from iesiri_valuta.py
    intrari_valuta.py
    registru_casa.py
    jurnal_banca.py
    deconturi.py
    imobilizari.py
    transferuri.py
    bonuri_consum.py
    productie.py
    inventariere.py
    comenzi.py
    contracte.py
    efactura.py
    cecuri.py
    diurne.py
    numere_serii.py
  partners.py           # keep as a compatibility shim for existing tool names
  fx_invoice_pdf.py     # exists
```

### 3.2 `protocol.py` — response handling (single place)

```python
Outcome = Literal["success", "needs_check", "needs_choice", "warning", "error"]

@dataclass(frozen=True)
class SagaResponse:
    outcome: Outcome
    raw: Any
    message: str | None
    flag_id: str | None
    validation_flags: list[dict]
    new_id: str | None

def classify(body: Any) -> SagaResponse:
    """Unify the two families:
       classic: {type: Validation|Choice|Warning, status, flagId}
       ex:      {success: bool, errorCode: 'ValidateData', validationFlags: [...]}"""

def post_with_handshake(page, url, payload, *, style, allow_choices: bool) -> SagaResponse:
    """1) POST with _CHECKED=false
       2) Validation → repost _CHECKED=true
       3) Choice     → only if allow_choices (i.e. confirm_write=true), repost with uvf
       4) Warning    → return as-is, never auto-answer
       Max 3 round trips, always return the full chain for diagnostics."""
```

Existing behaviour to fold in: `iesiri_valuta._post_with_validation_retry`, `iesiri_valuta._extract_created_ids`, `partners._post_clienti_row`, `partners._delete_clienti_via_api`.

### 3.3 `grid.py` — the generic client

```python
@dataclass(frozen=True)
class GridModel:
    table_name: str
    controller: str
    primary_key: str
    get_data_url: str
    create_url: str
    edit_url: str
    delete_url: str
    next_index_url: str | None
    copy_detail_url: str | None
    delete_master_details_url: str | None
    is_master: bool
    is_detail: bool
    master_table: str | None
    selection_key: str | None
    columns: tuple[GridColumn, ...]

class SagaGrid:
    def __init__(self, page, model: GridModel): ...
    def list(self, *, skip=0, batch_size=100, keyword=None, columns=None,
             search_type=1, sort_column=None, sort_mode=None,
             master_id=None) -> dict          # GET getData
    def get(self, pk: str) -> dict | None      # getData with id
    def next_index(self) -> str | None         # GET getNextIndex
    def create(self, row: dict, *, allow_choices: bool) -> SagaResponse
    def update(self, pk: str, row: dict, *, allow_choices: bool) -> SagaResponse
    def delete(self, pk: str, *, allow_choices: bool) -> SagaResponse
    def details(self, master_pk: str, detail_table: str) -> dict
    def create_detail(self, master_pk: str, detail_table: str, row: dict, *, allow_choices) -> SagaResponse
    def copy_detail(self, origin_id, target_id, negative=False) -> dict
```

Rules baked into `SagaGrid`:
- Never send a column that is not in `model.columns` — return `unknown_fields` instead (mirrors today's `_map_user_fields`).
- Never invent values. Only fill `defaultValue` when SAGA's own model declares one, and say so in the result.
- Auto-`next_index` when `avoidPKGeneration` is false or the table is one of `Intrari|Iesiri|IntrariValuta|IesiriValuta`.
- Every mutating call returns `{ok, via, endpoint, request, response_chain, screenshot_path, capture_path}` so failures are debuggable without re-running.

### 3.4 `discovery.py` — one probe to rule them all

```python
def probe_screen(page, route: str) -> dict:
    """Navigate to <app_base>/<route>, capture every tableModel on the page,
       return grids (model + columns + combos), toolbar buttons, detected
       report buttons, and the raw XHR capture. Persist to
       data/saga/research/tablemodels/<route>.json"""
```

This becomes an MCP tool (`saga_probe_screen`, read-only) so the **agent itself can onboard a new SAGA screen** without a code change — that is the mechanism that gets us to 100% coverage cheaply.

`registry.py` then holds the curated, reviewed result:

```python
SCREENS: dict[str, ScreenSpec] = {
  "clienti": ScreenSpec(route="Clienti", controller="Clienti", table="Clienti",
                        pk="Cod", risk="low", tools=("list","get","create","update","delete","export")),
  "iesiri_valuta": ScreenSpec(route="IesiriValuta", controller="IesiriValuta",
                        table="IesiriValuta", detail_table="IesiriValutaDetalii",
                        pk="ID_Iesire", risk="medium", tools=(...)),
  ...
}
```

### 3.5 Generic MCP tool surface

These 12 tools alone cover the read/write/export/report needs of **every** grid-based screen:

| Tool | Kind | Purpose |
|---|---|---|
| `saga_context` | read | firm, user, period, accounting type, rights (`LoadOperationalData` + `LoadDrepturiEcrane`) |
| `saga_list_screens` | read | curated registry: which SAGA screens Markus can drive, and at what risk level |
| `saga_probe_screen` | read | discover `tableModel`/columns/endpoints for a screen; the onboarding tool |
| `saga_describe_screen` | read | writable columns + types + combos + required fields for a screen (generic `*_fields`) |
| `saga_list_rows` | read | paged/filtered read of any registered grid |
| `saga_get_row` | read | single row by PK |
| `saga_lookup` | read | combo values for a column (`GetData_ComboBox_*`) |
| `saga_create_row` | write | create on any registered grid; `confirm_write` gate |
| `saga_update_row` | write | update; only user-specified fields |
| `saga_delete_row` | write | delete; `confirm_write` gate |
| `saga_create_document` | write | master + detail lines in one call (journals/documents) |
| `saga_export_grid` | read | `Home/ExportDate` → xlsx path |
| `saga_run_report` | read | `Rapoarte/SetDataRaport<X>` + `CreateRaport<X>` → pdf/xls path |
| `saga_validate_document` | write | `ExecutaValidare` / `ExecutaDevalidare`; `confirm_write` gate |

Plus **named convenience wrappers** for the high-traffic screens (better agent ergonomics and stable names for skills), e.g. `saga_list_suppliers`, `saga_create_supplier`, `saga_list_items`, `saga_create_item`, `saga_add_intrare`, `saga_add_iesire`, `saga_add_iesiri_valuta` (exists), `saga_add_casa_entry`, `saga_add_bank_entry`, `saga_trial_balance`, `saga_account_ledger`, `saga_sales_journal`, `saga_customer_statement`, `saga_stock_report`, `saga_efactura_list`, `saga_efactura_download`.

Backwards compatibility: keep every currently shipped tool name (`saga_list_partners`, `saga_create_partner`, `saga_add_iesiri_valuta`, …) as thin wrappers over the generic layer. Update `tools/catalog.py` in the same commit as `server.py` — the catalog is what `list_tools` reports and it has drifted before.

---

## 4. Complete feature → tool mapping (all 77)

Legend for **Plan**: `G` = covered by the generic grid tools + registry entry only · `A` = generic + a thin adapter · `R` = report tool (`saga_run_report`) · `H` = human-gated (tool exists but requires explicit confirmation and never runs unattended) · `✓` = already shipped.

### 4.1 Auth / Session (4)

| Feature | Route/Controller | Plan | Notes |
|---|---|---|---|
| Login | `Home/Login`, `Home/CompleteLogin` | ✓ | `saga_login` |
| OTP / browser authorize | `Home/ValidateOTP` | ✓ | `saga_submit_otp`; email link is the user's side-channel |
| Firm select | `/Firme` + Conectare | ✓ | inside `saga_login` |
| Working interval | `Home/LoadOperationalData` | A | new `saga_context` read; changing interval = toolbar UI action, add `saga_set_interval` with confirm |

### 4.2 Fisiere — master data (12)

| Feature | Controller / Table | Plan | Adapter work |
|---|---|---|---|
| Clienti | `Clienti` | ✓ | migrate to generic; keep tool names |
| Furnizori | `Furnizori` | A | `Verificare`, `VerificareAll`, `LProcedure_Furnizori`, `Home/GetBanca` — mirror of Clienti |
| Agenti | `Agenti` | G | pure nomenclator |
| Plan conturi | `PlanConturi` | A | `LProcedure`, `GetTipSintetic`, `VerifAnalitic121`; add `saga_chart_of_accounts` read |
| Gestiuni | `Gestiuni` | A | `GetNextPK`, `LProcedure` |
| Tipuri de articole / servicii | `TipuriArticole` | A | `AnteEdit`, `ActualizeazaTipArticole` |
| Articole | `Articole` | A | biggest adapter: `GetTVAArticol`, `IsVandabil`, `CheckSGR`, `GenereazaCB`, `GetBrut`/`SetBrut`, `UpdateGarantie`, `PreturiVanzare/*` |
| Grupe | `Grupe` | A | `LProcedure_{Articole,Clienti,Furnizori,Proiecte,BugCategorie}` |
| Filiale | `Filiale` | A | `GetCod`, `LProcedure_Filiale` |
| Salariati | `Salariati` | H | `access=1` today; read-only until rights granted |
| Actionari | `Actionari` | A | `GetNextCod`, `ExecutaGenerarePDF` |
| Masini | `Masini` | A | `RefDate`, `SetFiltruTip`; reports `FoaieParcursPDF`, `SituatieCosturiMasiniPDF` |

### 4.3 Operatii — journals (24)

| Feature | Controller / Tables | Plan | Adapter work |
|---|---|---|---|
| Articole contabile | (probe) | G | probe first; likely `Registru` grid |
| Intrari | `Intrari` + `IntrariDetalii` | A | `GetTextFurnizor`, `SetIdBcIntrariDetalii`, `ExecutaValidare/Devalidare`, `Home/ExecutaInsMMod`, NIR reports |
| Iesiri | `Iesiri` + `IesiriDetalii` | A | `GetTextClient`, `GetCAG`, `CorectezTVA`, validare, `Rapoarte/AnteCheckFacturaCuChitanta` |
| e-Facturi | `EFactura` (`EFactImport`, `EFactImportDetalii`, `EFactRaspunsuri`, `EFactGenerareSiTransmitere`, `EFactImportFacturiEmise`) | A/H | read+download automatable; **ANAF submit/cancel is `H`** (`ImportEFactura`, `AnulareEFactura`, `SalveazaDate_EFactGenerareSiTransmitere`, token via `ReadToken`/`SaveToken`/SPV code) |
| Intrari - valuta | `IntrariValuta` (+`Detalii`) | A | mirror of IesiriValuta; `GetCursValutar` lives here |
| Iesiri - valuta | `IesiriValuta` (+`Detalii`) | ✓ | migrate onto `grid.py`, keep `saga_add_iesiri_valuta` |
| Imobilizari | `Imobilizari` | A | `GetNrInventar`, `ValoareRamasa`, `RI_S`, validare, 5 report variants |
| Transferuri | `Transferuri` | A | `GetNrDoc`, `GetCAT`, `ValidareCantitate`, `InsertSelectiiRapide`, validare |
| Bonuri de consum | `Bonuri` / `BonuriOI` | A | `Bonuri/GetCAG`, `BonuriOI/CompareDatePrelGest`, validare |
| Productie | `Productie` | A | `GetNrDoc`, `GetNrDocComenzi`, `GetValDescNoStoc`, validare (+Master) |
| Inventariere | `Inventariere` | A | `GetNrDoc`, `ValidPret`, `ActualizareStocuriScriptice`, `SetFiltreDetalii`, validare |
| Dare în folosinta ob. inv. | `BonuriOI` | A | shares the Bonuri adapter |
| Dezmembrari | (probe) | H | stock teardown; destructive |
| Operatii speciale | (probe) | H | rare corrective ops |
| Reglari descarcare | (probe) | H | stock adjustments |
| Registru de casa | `RegistruCasa` | A | largest cash adapter (see §1.8); receipts via `RegistruCasaChitantaPDF` |
| Registru de casa - valuta | `RegistruCasa` (valuta mode) | A | same adapter + `GetLastValuta`, `SetContDifCurs` |
| Deconturi | `RegistruCasa` family / `Deconturi` view | A | `JurnalDeconturiPDF`, `AnteCheckDecont` |
| Deconturi - valuta | idem | A | `JurnalDeconturiValutaPDF` |
| Jurnal de banca | `RegistruCasa` family / `JurnalDeBanca` view | A | `JurnalBancaPDF`, `BorderouPDF`, `SetFiltruOP`, `AnteCheckIBAN` |
| Jurnal de banca - valuta | idem | A | `JurnalBancaValutaPDF` |
| Cecuri, BO emise/primite | `Cecuri` | A | `Cecuri/SetAnteSaveData` (already referenced inside AdvancedControls) |
| State salarii | `StateSalarii` | H | `access=1`; payroll + D112 filings |
| Inchidere luna | `InchidereLuna` | H | irreversible period close; expose read-only status (`GetInchidereCurenta`) + a hard-gated execute |

### 4.4 Situatii — reports (23)

All of these are the same tool with different parameters. Build **one** `saga_run_report` plus a small registry mapping friendly name → (setter endpoint, creator endpoint, filter schema). Named wrappers for the top ones.

| Feature | Setter → Creator | Plan |
|---|---|---|
| Fise conturi | `SetDataRaport…` (probe `FiseConturi` combos) → `…PDF` | R |
| Balante | `Balanta/ExecutaBalanta` + `SetDataRaportBalanta` → `CreateRaportBalantaPDF` | R |
| Carte mare | probe | R |
| Jurnale de cumparari / vânzari | `SetDataRaportIntrari` / `SetDataRaportListaIesiri` → `IntrariPDF` / `ListaIesiri` | R |
| Situatie furnizori | probe (`SituatiiFurnizori` view) | R |
| Situatie clienti | probe (`SituatiiClienti` view) | R |
| Situatie cecuri / bilete la ordin | probe (`Cecuri`) | R |
| Registru jurnal | probe | R |
| Registru inventar | `ImobilizariRegistruPDF` family | R |
| Bilant | `Bilant/*` + `SetDateRaportBilant` → `BilantDeclaratiePDF`, `BilantNota1..10PDF` | A+R |
| Declaratia 406 (SAF-T) | `Declaratia406` | H |
| Declaratia 205 | `Home/GetViewDeclaratia205` | H |
| Declaratia Intrastat | probe | H |
| Fise articole | `SetDateRaportArticole` → `ArticolePDF` | R |
| Situatie aprovizionari | `SituatiiAprovizionari` combos | R |
| Situatie vânzari | `SituatiiVanzari` combos → `ListaIesiri` | R |
| Situatie consumuri | `SetDataRaportConsumuri` → `ConsumuriPDF` | R |
| Situatie obiecte inventar | → `OIPDF` | R |
| Situatie productie | `SetDataRaportProductie` → `ProductiePDF` | R |
| Situatie stocuri | → `StocBCPDF` / `SituatieMarfuri` | R |
| Situatie ambalaje SGR | `Articole/CheckSGR` + probe | R |
| Raport de gestiune | probe | R |
| Situatii manageriale | `SituatiiManageriale` combos, `SitLunare` → `SituatiiLunarePDF` | R |

### 4.5 Diverse (8)

| Feature | Controller | Plan | Notes |
|---|---|---|---|
| Comenzi | `Comenzi` | A | orders master+detail; `ComandaIesirePDF`/`ComandaIntrarePDF`; shares Articole+Productie helpers |
| Situatie comenzi | `Rapoarte/SetDataRaportAnexaComanda` | R | |
| Contracte | `Contracte` | A | `GenerareFacturi` is a **write with financial impact** → `confirm_write` + preview of what would be invoiced |
| Cheltuieli / venituri în avans | `InregistrareCheltuieliVenituri` | A | `Home/GetViewInregistrareCheltuieliVenituri` |
| Import date | `ImportDate` | H | `UploadXMLFiles`/`ImportFactura` can corrupt ledgers |
| Diurne | probe | A | per-diem grid; `OrdinDeDeplasarePDF` |
| e-Transport | `eTransport` | H | ANAF portal |
| REVISAL | `REVISAL` | H | labour registry filing |

### 4.6 Administrare (6)

| Feature | Controller | Plan |
|---|---|---|
| Configurare societati | `ConfigSociet` | H (read via `LoadOperationalData.Societ` is fine) |
| Configurare salarii | payroll config | H (`access=1`) |
| Numere si serii | probe | A — needed by document tools to pick the right series |
| Utilizatori | probe | H — security |
| Intretinere BD | `BackupDB`, `Home/UpdateDB` | H — destructive |
| Despre... | `Home/GetActualizari` | G — version info, trivially read-only |

---

## 5. Per-screen runbook (repeat verbatim for every new screen)

1. **Open + probe.** `saga_probe_screen(route)` → persist `tablemodels/<Route>.json`. Confirm `tableName`, `controllerName`, `primaryKey`, `actionsURLs`, `tableColumns`, detail table(s).
2. **Read first.** `SagaGrid.list(batch_size=5)` and eyeball the rows against the UI. If the shapes disagree, the model is wrong — fix before writing anything.
3. **Capture a real UI write.** Turn on `saga_session.clear_capture()`, perform ONE create in the UI by hand (or via Playwright toolbar clicks) on a throwaway record, then `_dump_capture("network-<screen>-create.json")`. This is the ground truth for the `RowData` keys, the `_CHECKED` sequence, and any side-effect calls that must run before/after (`LProcedure`, `AnteEdit`, `ExecutaInsMMod`).
4. **Diff.** Compare captured `RowData` against `tableColumns`. Anything present in the capture but absent from our payload is a required field or a server default we must reproduce.
5. **Replay via `page.request`.** Implement `create`/`update` with `post_with_handshake`. Verify the row comes back through `getData` — never trust the POST response alone.
6. **Detail lines** (documents only): create master, read PK from the `Validation` `status` / response, then create each line with the FK from `detailSetup.selectionKey`, then re-read the master row for computed totals.
7. **Deletes.** Test on the record created in step 5. Confirm both the POST and GET variants; record which one this controller accepts in the registry.
8. **Register.** Add the `ScreenSpec` to `registry.py`, add named wrapper tools to `server.py` **and** the matching `ToolInfo` to `tools/catalog.py`.
9. **Document.** Append a short "endpoints used" section to this plan's appendix and store the capture JSON next to it.

Throwaway-record discipline: every screen gets a `MARKUS-TEST-<timestamp>` record created and deleted in the same session, so we never learn a protocol on real accounting data.

---

## 6. Guardrails (non-negotiable)

- **Preview-then-confirm on every mutation.** Same contract as today: call with `confirm_write=false` → returns `{requires_confirmation: true, preview, mapped_fields}`; only `confirm_write=true` writes. Applies to create/update/delete, document creation, `ExecutaValidare`, `Contracte/GenerareFacturi`, e-Factura submit.
- **Never auto-answer a `Choice`.** A `Choice` is SAGA asking a human a question. Auto-answering is only allowed when the user already confirmed the write, and the question text must be echoed in the tool result.
- **Never invent field values.** Only send keys the caller supplied, plus documented SAGA defaults, and always report which values were auto-filled and why (existing `iesiri_valuta` behaviour for `Tip`/`Curs`/`NrDoc` is the model).
- **Human-only list** (tools may read, must not write unattended): `Inchidere luna`, `State salarii`, `Configurare salarii/societati`, `Utilizatori`, `Intretinere BD`, `Import date`, `Declaratia 406/205/Intrastat`, `e-Transport`, `REVISAL`, `Dezmembrari`, `Operatii speciale`, `Reglari descarcare`, e-Factura ANAF submit/cancel.
- **Rights-aware.** Check `LoadDrepturiEcrane` before offering a screen; return a clear "your SAGA user lacks rights for X" instead of a cryptic HTTP failure.
- **Period-aware.** Refuse writes dated inside a closed period; surface `InchidereLuna/GetInchidereCurenta`.
- **Every mutating tool returns** endpoint, request payload, full response chain, screenshot path and network capture path. Debuggability is part of the contract.
- **Concurrency.** All SAGA work runs on the single browser worker thread (`session._run_on_browser_thread`). Do not add a second context; SAGA's session and `tabID` are per-browser.

---

## 7. Rollout waves

| Wave | Scope | Exit criteria |
|---|---|---|
| **0 — Foundation** | `protocol.py`, `discovery.py`, `grid.py`, `registry.py`, `context.py`; migrate `Clienti` + `IesiriValuta` onto it with **zero tool-name changes**; add `saga_probe_screen`, `saga_context`, `saga_describe_screen` | existing FX-invoice skill passes end-to-end unchanged; `saga_probe_screen("Clienti")` reproduces the known endpoints |
| **1 — Master data** | Furnizori, Agenti, PlanConturi, Gestiuni, TipuriArticole, Grupe, Filiale, Actionari, Masini, Articole | create+read+update+delete verified with a throwaway record on each |
| **2 — Generic read/export/report** | `saga_list_rows`, `saga_get_row`, `saga_lookup`, `saga_export_grid`, `saga_run_report` + report registry | all 23 "Situatii" features produce a file on disk |
| **3 — Sales & purchases** | Iesiri, Intrari, IntrariValuta (+ validate/devalidate), Numere si serii | a full invoice (header+lines+VAT) round-trips and matches the UI totals |
| **4 — Cash, bank, expenses** | RegistruCasa (+valuta), Jurnal de banca (+valuta), Deconturi (+valuta), Cecuri | receipts/payments post and reconcile; chitanta PDF generated |
| **5 — Stock & production** | Transferuri, Bonuri de consum, BonuriOI, Productie, Inventariere, Imobilizari | stock documents post and validate |
| **6 — Commercial** | Comenzi, Contracte, Cheltuieli/venituri în avans, Diurne, Situatie comenzi | `Contracte/GenerareFacturi` gated preview works |
| **7 — e-Factura (read side)** | list/download inbound, import status, error queues | inbound invoices downloadable; submit remains human-gated |
| **8 — Gated screens** | Bilant, Inchidere luna, Salariati/StateSalarii, declarations, Administrare | read-only + hard-gated execute paths, with explicit user confirmation text |

Each wave ends with: `pyproject.toml` version bump, `tools/catalog.py` updated in the same commit as `server.py`, and a smoke run of `list_tools`.

---

## 8. Testing & verification

- **Protocol unit tests** on recorded fixtures: feed saved JSON bodies into `protocol.classify` and assert the outcome (`Validation` → repost, `Choice` → gated, `ValidateData` → flags, `success` → done).
- **Discovery snapshot tests**: `tablemodels/<Route>.json` committed; a test asserts the registry's endpoints still match the snapshot, so a SAGA UI update fails loudly instead of silently.
- **Live round-trip test per screen** (manual, once per wave): create throwaway → read back → update → read back → delete → confirm gone.
- **Golden document test**: the existing `data/fake_invoice_K003_FAKE_NORD_LOGISTICS.pdf` import must keep working after every wave — it exercises session, partner lookup, partner create, FX rate, document header+lines, and the WhatsApp notify skill.
- **Never test on real accounting data.** Test firm or `MARKUS-TEST-*` records only.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| SAGA ships a UI update and changes `RowData` keys | discovery is runtime-first (`tableModel`), snapshots make drift a loud test failure rather than a silent bad write |
| A `Choice` auto-answered wrongly writes bad accounting data | never auto-answer without `confirm_write=true`; echo the question text in the result |
| Reports depend on server-side session state (`SetDataRaport` then `CreateRaport`) — two agents interleaving would cross filters | all SAGA work is serialized on the single browser worker; keep it that way |
| `Descarca=true` returns HTML error pages instead of PDF | validate `content-type`/magic bytes before writing the file; return the HTML as `error_html` when it isn't a PDF |
| Restricted rights (`access=1`) look like generic failures | pre-flight `LoadDrepturiEcrane` and return a specific message |
| Session expiry mid-workflow | `Home/IsStillConnected` before long workflows; auto re-login only when it does not require OTP |

---

## 10. Appendix — raw research index

Source files under `data/saga/research/`:

- `AdvancedControls.min.js` — the grid engine: `parseTableModel`, `getData`, `toolbarActionSave`, delete handshake, `getNextIndex`, `copyDetail`, `Home/ExportDate`, `Home/GetAdvancedComboBoxViewComponent`.
- `Layout.min.js` — shell: `Home/LoadOperationalData`, `LoadDrepturiEcrane`, `IsStillConnected`, `Balanta/ExecutaBalanta`, `BackupDB/*`, `EFactura/SaveToken`.
- `modules/*.js` (40 files) — per-screen business endpoints; the inventory in §1.8/§1.9 was extracted from these.
- `feature_inventory.json` / `feature_inventory_compact.json` — 77 features with access flags and feasibility.
- `_menu.json` — RO/EN labels for every screen (use for tool descriptions so agents can match Romanian user phrasing).
- `_pages.json`, `_modals.json`, `_common.json` — RO/EN UI string dictionaries (useful for matching modal/warning text in `Choice`/`Warning` responses).
- `data/saga/network-*.json` — live captures already recorded for login, partners, partner create/update/delete, IesiriValuta probe and create.
