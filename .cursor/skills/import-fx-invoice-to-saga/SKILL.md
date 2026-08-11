---
name: import-fx-invoice-to-saga
description: >-
  Import a readable PDF sales invoice into SAGA WEB foreign invoices (IesiriValuta)
  via Markus MCP: detect currency, extract fields, ensure partner exists, create FX
  invoice, summarize steps, then WhatsApp-notify Eu. Use when the user gives a PDF
  path and asks to put/add/import that invoice into SAGA (foreign / FX /
  IesiriValuta / valuta).
---

# Import FX invoice PDF into SAGA

When the user gives a **PDF path** and asks to put that invoice into SAGA, run this
workflow end-to-end with **Markus MCP** (`user-markus`). Do not skip steps.

Assumption for now: the PDF is **text-readable** (not a scan/image).

The user's request to run this import **authorizes** partner create, FX invoice
create, and the WhatsApp notify at the end. Still call mutations with a
`confirm_*=false` preview first, then immediately `confirm_*=true` to execute
(unless a preview shows a clear problem — stop and ask).

## Checklist

```
- [ ] 1. Read PDF → currency RON vs foreign
- [ ] 2. If foreign → extract SAGA FX fields
- [ ] 3. saga_status / saga_login (pause for email auth / OTP if needed)
- [ ] 4. Find partner (search/get)
- [ ] 5. Create partner if missing
- [ ] 6. saga_add_iesiri_valuta
- [ ] 7. Short chat summary of tools + steps
- [ ] 8. WhatsApp Eu
```

## Step 1 — Read PDF and detect currency

1. Read the PDF at the given path (workspace Read tool / file tools).
2. Detect currency from labels and amounts (`Currency`, `Valuta`, `EUR`, `USD`,
   `GBP`, `CHF`, `RON`, etc.).
3. Branch:
   - **Foreign (not RON)** → continue.
   - **RON only** → stop. Tell the user this skill only imports **foreign**
     invoices into IesiriValuta for now; do not call `saga_add_iesiri_valuta`.

## Step 2 — Extract fields for `saga_add_iesiri_valuta`

Extract from the PDF yourself (do **not** rely on an in-MCP LLM key).

Use `saga_iesiri_valuta_fields` if unsure of names/aliases.

**Header (required):**

- `Client` and/or `Cod` (customer name; code if present)
- `Valuta` (e.g. `EUR`)
- `Data` as `dd.mm.yyyy`
- Prefer also: `NrDoc`, `Scadent`

**Each line (required):**

- `Cont` — revenue account; PDF usually lacks this. Default **`704`** for
  services / consulting unless the user or PDF clearly implies goods (`707`)
- `Denumire`
- `Cantitate` + `PretUnitarValuta` (or explicit line amounts)
- Prefer: `UM`, `TVA_ART` (use rates valid for `Data`, e.g. 0/11/21 — not stale 19
  when SAGA rejects it)

Do not invent optional fields. Map only what the PDF supports (+ `Cont` default).

## Step 3 — SAGA login

1. Call `saga_status`.
2. If not logged in / firm not selected → `saga_login`.
3. Handle auth pauses (do **not** abandon the import; resume from step 4 after login
   succeeds):

### 3a — Browser authorization (`needs_browser_authorization=true`)

This is the preferred path (3-month browser trust).

1. **Stop tool calls** and message the user clearly:
   - SAGA sent an authorization email (include `authorization_request_id` if
     present, e.g. `AUTH-…`).
   - Open that email and click **Autorizează browser**.
   - Do **not** click **Autentificare fără autorizare** (that forces OTP every
     login).
   - Reply here when done (e.g. “done” / “authorized”).
2. **Wait** for the user’s reply. Do not call `saga_login` again until they
   confirm, and do not ask them to paste passwords into chat.
3. After they confirm → call `saga_login` again.
4. If still unauthorized → remind them and wait again. If they explicitly ask for
   the one-time OTP path → `saga_login(allow_otp_without_authorization=true)` and
   follow 3b.
5. When `logged_in` / firm-ready → continue the checklist from step 4 with the
   fields already extracted in step 2 (no need to re-read the PDF unless the
   conversation lost that context).

### 3b — OTP (`needs_otp=true`)

1. Ask the user for the 6-digit code from the SAGA email.
2. Wait for their reply, then `saga_submit_otp`.
3. On success → continue from step 4.

## Step 4 — Find partner

Identify the invoice **customer** (buyer / Bill To), not the seller.

1. Prefer `saga_search_partners` with name and/or CUI/VAT id.
2. Or `saga_list_partners` / `saga_get_partner` for an exact id/cod/name.
3. Require an **exact** match (name or CUI/cod). Near matches → ask the user;
   do not guess.

## Step 5 — Create partner if missing

If no exact partner:

1. `saga_partner_fields` if needed.
2. `saga_create_partner` with `confirm_write=false` using only PDF-backed fields
   (e.g. `Denumire`, `CodFiscal`/CUI, address if present).
3. Then `confirm_write=true`.
4. Keep the resulting `Cod` / name for the invoice header.

If the partner exists, set invoice `Cod` / `Client` from that partner record.

## Step 6 — Create FX invoice

1. `saga_add_iesiri_valuta` with `confirm_write=false` and the extracted
   `header` + `lines` (partner `Cod`/`Client` filled).
2. Review preview / mapped payload; fix missing `Cont` or VAT if SAGA would fail.
3. `saga_add_iesiri_valuta` again with `confirm_write=true`.
4. Record `NrDoc`, `ID_Iesire`, client name, currency, totals from the result.

## Step 7 — Chat summary

After success, reply with a **short** summary:

- PDF path + currency
- Partner: found vs created (name/cod)
- Invoice: number, date, valuta, line count, key ids
- MCP tools used (in order)
- WhatsApp notify status (step 8)

## Step 8 — WhatsApp notify Eu

WhatsApp is assumed paired and ready.

1. `send_whatsapp_message` with:
   - `to_name`: `Eu` (exact; never a near match)
   - `message`: short note that an invoice from **{company}** was added to
     foreign invoices (IesiriValuta) in SAGA (include `NrDoc` / currency if known)
   - `confirm_send=false`
2. Then `confirm_send=true` (authorized by this import request).

Example message:

```text
Salut — am adăugat în SAGA (IesiriValuta) factura de la {Company} ({NrDoc}, {Valuta}).
```

## Failure rules

- Stop on RON-only invoices (this skill).
- Stop if PDF cannot be read as text.
- Stop if partner match is ambiguous.
- On SAGA auth (`needs_browser_authorization` / `needs_otp`): pause, guide the
  user (step 3a/3b), wait for their reply, then continue the same import — do not
  treat auth as a hard failure or restart from scratch.
- If WhatsApp send fails after invoice success, still report SAGA success and the
  WhatsApp error separately.
