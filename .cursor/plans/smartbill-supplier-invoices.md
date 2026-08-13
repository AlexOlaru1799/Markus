# SmartBill → Markus MCP: supplier invoices (Documente furnizori)

Goal: add Markus MCP tools that list **supplier invoices** from SmartBill Cloud
([Documente furnizori](https://cloud.smartbill.ro/achizitii/raport/documente_furnizori/)),
filter them by a user period (“this month”, “last month”, “from 15 September”),
and export the selection as **Excel (.xls / .xlsx)**.

**API-first:** use the public REST API wherever it actually covers the job.
Do **not** open a browser unless the public API cannot list/export purchases.

Docs: [SmartBill Cloud API](https://api.smartbill.ro/). Help for the UI report:
[Documente furnizori](https://ajutorgestiune.smartbill.ro/article/546-documente-furnizori),
[Excel export on that report](https://ajutor.smartbill.ro/article/1157-descarcarea-e-facturilor-preluate-din-spv).

---

## 0. Finding (must drive the design)

The public API at `https://ws.smartbill.ro/SBORO/api/` is an **issuance** API for
**sales** documents. Published resources:

| Resource | Role |
|---|---|
| `POST /invoice` | Issue a sales invoice |
| `GET /invoice/pdf` | PDF of **one** sales invoice (`cif` + `seriesname` + `number`) |
| `GET /invoice/paymentstatus` | Payment status of **one** sales invoice |
| `DELETE /invoice`, `PUT /invoice/cancel`, `PUT /invoice/restore`, `POST /invoice/reverse` | Mutate one sales invoice |
| ` /estimate` | Proformas (same pattern) |
| ` /payment` | Receipts / payments |
| `POST /document/send` | Email a document |
| `GET /tax`, `GET /series` | VAT rates, document series |
| `GET /stock` (and similar) | Warehouse stock |

There is **no** documented endpoint for:

- listing invoices by date range
- **purchases / achiziții / documente furnizori**
- Excel / XLS export of a report

`GET /invoice/pdf` and `GET /invoice/paymentstatus` need **series + number** you
already know. They cannot answer “what arrived last month?”.

The page the user named is a **Cloud Gestiune report**. SmartBill’s own help
says that report has date filters and **Export Excel** (XLS, includes supplier
CIF). That export is a Cloud UI action, not a public REST method.

So:

1. **Auth, CIF, connectivity** → public REST API (no browser login).
2. **List + period filter + XLS** → Cloud report HTTP (same URLs the UI calls).
   Prefer calling those URLs with **HTTP + the API token**. Fall back to a
   persisted Cloud browser session **only if** the report APIs reject Basic Auth.

Do not try to reconstruct Documente furnizori by looping `GET /invoice/pdf` —
that is sales, keyed by series/number, and not supplier SPV docs.

---

## 1. Auth (no OTP / no “login page”)

Public API auth ([docs](https://api.smartbill.ro/)):

- **Basic Auth**, preemptive: `Authorization: Basic base64(email:token)`
- **email** = SmartBill Cloud login
- **token** = Contul Meu → Integrări → API (bottom of the page)
- Every public call also needs **`companyVatCode`** (firm CIF)
- HTTPS only; JSON or XML (`Accept` / `Content-Type`)
- Rate limit: **30 calls / 10 seconds** → 403 + 10 minute block
- Contact: `api@smartbill.ro`

There is **no session login, no OTP, no “authorize browser”** on the public API.
A `smartbill_login` tool that types into `cloud.smartbill.ro` is the wrong
default.

Store in `~/.markus/private.data` (same store as SAGA; never ask the user to
paste secrets into chat):

```text
smartbill_username = 'you@example.com'
smartbill_token    = '…'
smartbill_cif      = 'RO12345678'
```

Extend `credentials_store.KEY_ORDER` / `KNOWN_KEYS`. The macOS/Windows
installers prompt for an **optional** `smartbill_token` and write it via
`--set-credentials`. Email falls back to `saga_username` when
`smartbill_username` is empty. `smartbill_cif` can be added later in
`private.data` for live `GET /series`.

**MCP tool:** `smartbill_status` (not `smartbill_login`)

- Read credentials; if missing → `configured: false` + which keys are empty
- `GET https://ws.smartbill.ro/SBORO/api/series?cif={cif}` (documented, cheap)
- Return `ok`, HTTP status, series count (no secrets), rate-limit headers if present
- 401 → tell the user to check email / token / CIF in `private.data`

Optional later: `smartbill_login` **only** if Wave 1 proves Cloud report
endpoints need cookies. Then mirror SAGA: Playwright + `~/.markus/data/smartbill-session`.

---

## 2. Period language (agent + tool)

The MCP tool takes **ISO dates**. The agent maps user speech:

| User says | `date_from` | `date_to` |
|---|---|---|
| this month | first day of current month | today (or last day of month — pick one and document it; prefer **today** for “this month so far”) |
| last month | first day of previous month | last day of previous month |
| from 15 September | `YYYY-09-15` (year = current unless specified) | today |
| 15–20 September | `YYYY-09-15` | `YYYY-09-20` |

Pass `date_from` / `date_to` as `YYYY-MM-DD` (SmartBill public API date format).
Do not send “last month” as a string to SmartBill.

---

## 3. Wave 0 — capture the real report API (blocking)

Before writing list/export tools, capture what
`https://cloud.smartbill.ro/achizitii/raport/documente_furnizori/` actually calls.

1. Log into Cloud in a browser (manual, once).
2. Open Documente furnizori, set a date filter, load the grid, click **Export Excel**.
3. Save HAR / `data/smartbill/network-documente-furnizori.json` (same idea as SAGA captures).

Record for **list** and **export**:

- URL, method, query/body (date fields, pagination, Salvate vs Nesalvate)
- Auth: cookie vs `Authorization: Basic` vs CSRF header
- Response shape (JSON rows vs HTML vs file bytes)
- Whether Export Excel is a separate download URL or client-side from the JSON

**Decision after capture:**

| Capture result | Implementation |
|---|---|
| Report URL accepts **same Basic email:token** (+ CIF) | Pure HTTP client. **No Playwright.** |
| Report URL needs Cloud **session cookies** | Playwright persistent profile (SAGA pattern), `page.request` replay |
| Export is a file URL with the same auth as list | Download that file as the XLS |
| Export is UI-only / blob built in JS | Build `.xlsx` ourselves from the list JSON (openpyxl). Still “API data”, not a fake scrape of HTML tables. |

Ask `api@smartbill.ro` in parallel whether a purchases/report endpoint exists or
is planned. If they add one, swap the captured URL for the documented one.

---

## 4. Tools (user-facing)

v1 is **read + export only**. No create/cancel of supplier docs.

### `smartbill_status`

Connectivity against the **public** API (`GET /series`). See §1.

### `smartbill_list_supplier_invoices`

List Documente furnizori rows for a period.

Inputs (draft):

- `date_from`, `date_to` (`YYYY-MM-DD`) — required
- optional: `section` (`saved` / `unsaved` / `all`) matching Salvate / Nesalvate
- optional: `limit`

Output: `{ ok, count, date_from, date_to, invoices: [ … ] }`

Row fields to keep if the report returns them (from SmartBill help):

- document type, series, number
- supplier name, supplier CIF (Excel has CIF as its own column)
- document date, due date
- category, net, VAT, total, currency
- saved vs unsaved / e-Factura status if present

Preview-style: this is read-only; no `confirm_write`.

Cap the payload (e.g. 200 rows in the tool result) and say `truncated: true`
if needed. Full set still used for export.

### `smartbill_export_supplier_invoices_xls`

Same period (and optional section) as list.

- Write file under `~/.markus/data/smartbill/`
- Name like `Facturi-achizitii-{from}-{to}.xls` (or `.xlsx` if we generate it)
- Return `path`, `row_count`, `date_from`, `date_to`

Prefer **SmartBill’s own Excel** when the captured export URL works (help says
`.XLS` and extra CIF column). If we generate the file, use `.xlsx` and the same
columns as the list tool.

Not a ledger mutation; no confirm gate unless the download is destructive
(it should not be).

Agent flow:

1. `smartbill_status` if not recently ok
2. Parse period → `date_from` / `date_to`
3. `smartbill_list_supplier_invoices` → show count + short table in chat
4. `smartbill_export_supplier_invoices_xls` → give the file path

---

## 5. Code layout (Markus)

New package, HTTP-first, no browser in the default path:

```text
src/markus_mcp/tools/smartbill/
  __init__.py
  credentials.py   # read username/token/cif from private.data
  client.py        # Basic Auth, JSON, rate-limit, public GET /series
  supplier_docs.py # list + export (public token or captured Cloud URL)
```

- Register tools in `server.py`; add to `catalog.py`
- `health_check`: `"smartbill_tools": true` when the module is loaded
- Server instructions: credentials from `private.data`; status then list then export
- Optional Cursor skill later: “export SmartBill supplier invoices for {period}”

Do **not** add `smartbill-rest-sdk` unless it saves a lot of code. v1 is three
calls; a thin `httpx`/`urllib` client is enough and avoids a dependency that
does not cover purchases anyway.

Tests: mock HTTP for status / list / export filename. No live SmartBill in CI.

---

## 6. What we will not do in v1

- Issue sales invoices via `POST /invoice` (out of scope)
- ANAF SPV download zip (XML/PDF archive) — different Cloud action
  (“Descarcă e-Facturi preluate”); add only if asked
- Scraping the HTML table as the source of truth
- Storing the API token anywhere except `private.data`

---

## 7. Rollout

1. **Wave 0 — capture** (one working Cloud session): HAR for list + Excel export;
   decide token vs cookies. **Implemented as live capture** on first
   `smartbill_list_supplier_invoices` (`~/.markus/data/smartbill/network-documente-furnizori.json`).
2. **Wave 1 — credentials + `smartbill_status`** against `GET /series`. **Done.**
3. **Wave 2 — list** with `date_from` / `date_to` (or `period=`). **Done** via Cloud UI
   (public API has no purchases list; 401/404 on `/purchase`).
4. **Wave 3 — XLS export** (native download or generated `.xlsx`). **Done.**
5. **Wave 4** — Playwright Cloud login is the list/export path (not optional).
6. **Wave 5 — SAGA Facturi XML** via `smartbill_invoices_to_saga_xml` (Flask
   `process_invoices_to_xml` rules: NIR required, skip CIF starting with `RO`).
   **Done.** Stripe / Trendyol / balanță processors from that app are not MCP tools.

Stop after Wave 0 if the capture is ambiguous; do not guess endpoints.

---

## 8. Open questions (resolve in Wave 0)

- Does the Documente furnizori XHR accept `Authorization: Basic` with the API token?
- Exact date query params (issue date vs due date vs SPV receive date).
- Salvate vs Nesalvate: default to **both**, or Salvate only (help: default UI
  hides receipts / payment orders / bank statements).
- Export MIME: real `.xls` vs `.xlsx`. Keep the extension SmartBill returns.
- Pagination / max rows for a month.
- Multi-firm: one `smartbill_cif` is enough for v1.
