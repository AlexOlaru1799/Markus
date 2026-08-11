from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode, urljoin

from markus_mcp.tools.saga import session as saga_session


ROUTE = "IesiriValuta"
GET_DATA_PATHS = (
    "IesiriValuta/GetData_IesiriValuta",
    "IesiriValuta/GetData",
)
CREATE_PATHS = ("IesiriValuta/Create_IesiriValuta",)
CREATE_DETAIL_PATHS = (
    "IesiriValuta/Create_IesiriValutaDetalii",
    "IesiriValutaDetalii/Create_IesiriValutaDetalii",
)
GET_DETAIL_PATHS = (
    "IesiriValuta/GetData_IesiriValutaDetalii",
    "IesiriValutaDetalii/GetData_IesiriValutaDetalii",
)


# Header fields agents may pass (aliases → SAGA name).
HEADER_FIELD_CATALOG: dict[str, dict[str, Any]] = {
    "NrDoc": {"aliases": ("nr_doc", "number", "invoice_number", "nr"), "kind": "text", "description": "Document number"},
    "Data": {"aliases": ("data", "date", "invoice_date"), "kind": "date", "description": "Document date (dd.mm.yyyy)"},
    "Scadent": {"aliases": ("scadent", "due_date"), "kind": "date", "description": "Due date"},
    "Tip": {"aliases": ("tip", "tip_factura", "invoice_type"), "kind": "combo", "description": "Invoice type"},
    "Cod": {"aliases": ("cod", "cod_client", "client_code"), "kind": "text", "description": "Client code"},
    "Client": {"aliases": ("client", "denumire_client", "customer", "customer_name"), "kind": "combo", "description": "Client name"},
    "Valuta": {"aliases": ("valuta", "currency"), "kind": "combo", "description": "Currency code (e.g. EUR, USD)"},
    "Curs": {"aliases": ("curs", "fx_rate", "exchange_rate"), "kind": "number", "description": "FX rate to RON"},
    "CodAgent": {"aliases": ("cod_agent", "agent_code"), "kind": "text", "description": "Agent code"},
    "Agent": {"aliases": ("agent", "agent_name"), "kind": "combo", "description": "Agent name"},
    "InformatiiSuplimentare": {
        "aliases": ("informatii_suplimentare", "explicatie", "notes", "description"),
        "kind": "text",
        "description": "Header notes",
    },
    "TipOperatie": {"aliases": ("tip_operatie",), "kind": "text", "description": "Operation type"},
    "FelD": {"aliases": ("feld", "fel_document"), "kind": "text", "description": "Document kind"},
    "TVAI": {"aliases": ("tvai",), "kind": "text", "description": "VAT on receipt flag/value"},
    "DataDocument": {"aliases": ("data_document",), "kind": "date", "description": "Related document date"},
}


# Line (IesiriValutaDetalii) fields.
LINE_FIELD_CATALOG: dict[str, dict[str, Any]] = {
    "Tip": {"aliases": ("tip", "tip_articol", "item_type"), "kind": "combo", "description": "Item type"},
    "Cod_Art": {"aliases": ("cod_art", "cod_articol", "article_code", "sku"), "kind": "text", "description": "Article/service code"},
    "Cod": {"aliases": ("cod",), "kind": "text", "description": "Article/service code (line Cod column)"},
    "Denumire": {
        "aliases": ("denumire", "denumire_articol", "item_name", "description"),
        "kind": "text",
        "description": "Article/service name",
    },
    "Gestiune": {"aliases": ("gestiune", "warehouse"), "kind": "combo", "description": "Warehouse"},
    "CodGestiune": {"aliases": ("cod_gestiune", "warehouse_code"), "kind": "text", "description": "Warehouse code"},
    "Cont": {
        "aliases": ("cont", "account", "cont_articol"),
        "kind": "combo",
        "description": "Revenue account (required by SAGA, e.g. 704 / 707)",
        "required": True,
    },
    "Cantitate": {"aliases": ("cantitate", "qty", "quantity"), "kind": "number", "description": "Quantity"},
    "UM": {"aliases": ("um", "unit"), "kind": "text", "description": "Unit of measure"},
    "PretUnitarValuta": {
        "aliases": ("pret_unitar_valuta", "unit_price_fx", "price_fx", "pret_valuta"),
        "kind": "number",
        "description": "Unit price in foreign currency",
    },
    "PretUnitar": {
        "aliases": ("pret_unitar", "unit_price_ron", "price_ron"),
        "kind": "number",
        "description": "Unit price in RON (auto from PretUnitarValuta * Curs when omitted)",
    },
    "TVA_ART": {
        "aliases": ("tva_art", "tva", "vat_rate"),
        "kind": "number",
        "description": "VAT rate % (use rates valid for Data — e.g. 0/11/21 from Aug 2025)",
    },
    "ValoareValuta": {
        "aliases": ("valoare_valuta", "line_total_fx"),
        "kind": "number",
        "description": "Line amount FX (usually calculated)",
    },
    "TVAValuta": {
        "aliases": ("tva_valuta", "vat_fx"),
        "kind": "number",
        "description": "VAT amount FX (usually calculated)",
    },
    "TotalValuta": {
        "aliases": ("total_valuta", "line_total_fx_with_vat"),
        "kind": "number",
        "description": "Line total FX with VAT (usually calculated)",
    },
    "Activitate": {"aliases": ("activitate",), "kind": "text", "description": "Activity / cost center"},
    "InformatiiSuplimentare": {
        "aliases": ("informatii_suplimentare", "inf_supl", "item_notes"),
        "kind": "text",
        "description": "Line notes",
    },
    "ID_U": {"aliases": ("id_u",), "kind": "text", "description": "Internal line uid (optional)"},
}


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().split()).casefold()


def _map_fields(payload: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    alias_to_name: dict[str, str] = {}
    for name, meta in catalog.items():
        alias_to_name[_normalize(name)] = name
        for alias in meta.get("aliases") or ():
            alias_to_name[_normalize(str(alias))] = name

    mapped: dict[str, str] = {}
    unknown: list[str] = []
    for key, value in (payload or {}).items():
        if value is None or str(value).strip() == "":
            continue
        saga_name = alias_to_name.get(_normalize(str(key)))
        if not saga_name:
            unknown.append(str(key))
            continue
        mapped[saga_name] = str(value).strip()
    return mapped, unknown


def fx_invoice_field_catalog() -> dict[str, Any]:
    return {
        "ok": True,
        "screen": "IesiriValuta",
        "url": f"{saga_session.DEFAULT_APP_BASE_URL}/IesiriValuta",
        "header_fields": [
            {"name": name, **{k: v for k, v in meta.items()}} for name, meta in HEADER_FIELD_CATALOG.items()
        ],
        "line_fields": [
            {"name": name, **{k: v for k, v in meta.items()}} for name, meta in LINE_FIELD_CATALOG.items()
        ],
        "usage": {
            "header": "Required: Client or Cod, Valuta, Data. Optional: Scadent, NrDoc, Tip, Curs, Agent, notes.",
            "lines": (
                "Required per line: Cont, and amounts (Cantitate + PretUnitarValuta, or explicit totals). "
                "Also useful: Denumire, Cod_Art/Cod, UM, TVA_ART, Gestiune."
            ),
            "confirm_write": "Call saga_create_fx_invoice with confirm_write=false first, then true after user OK.",
            "endpoint": "POST IesiriValuta/Create_IesiriValuta (+ Create_IesiriValutaDetalii) with RowData JSON.",
        },
        "notes": [
            "Tip '' = Factura (default). Other codes from GetData_ComboBox_Tip_Iesiri (T, A, S, …).",
            "Cont is mandatory on each line (SAGA warning: Nu ati ales contul).",
            "FX rate Curs is auto-fetched from IntrariValuta/GetCursValutar when omitted.",
        ],
    }


def _ready(page):
    from markus_mcp.tools.saga import partners as saga_partners

    return saga_partners._ready(page)


def _resolve_client(page, header: dict[str, str]) -> dict[str, str]:
    """Ensure Cod + Client are populated when either is provided."""
    from markus_mcp.tools.saga import partners as saga_partners

    out = dict(header)
    if out.get("Cod") and out.get("Client"):
        return out
    key = out.get("Cod") or out.get("Client") or ""
    if not key:
        return out
    # Prefer in-session search without nested run_in_session: reuse partner helpers on page.
    opened = saga_partners._open_partners_ui(page)
    if not opened.get("ok"):
        return out
    probed = saga_partners._probe_data_endpoints(page, query=key)
    partners = saga_partners._rows_from_json((probed or {}).get("body")) if probed else []
    if not partners:
        partners = saga_partners._scrape_partner_table(page)
    partners = saga_partners._filter_partners(partners, key)
    exact = []
    for partner in partners:
        pid = saga_partners._partner_id(partner) or ""
        den = str(partner.get("Denumire") or partner.get("denumire") or "")
        if _normalize(pid) == _normalize(key) or _normalize(den) == _normalize(key):
            exact.append(partner)
    pick = exact[0] if len(exact) == 1 else (partners[0] if len(partners) == 1 else None)
    if not pick:
        return out
    if not out.get("Cod"):
        out["Cod"] = str(pick.get("Cod") or pick.get("cod") or "").strip()
    if not out.get("Client"):
        out["Client"] = str(pick.get("Denumire") or pick.get("denumire") or "").strip()
    return out


def _fetch_tip_factura(page, data: str) -> str:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", "IesiriValuta/GetMostUsedTipFactura")
    try:
        response = page.request.get(
            f"{absolute}?{urlencode({'data': data})}",
            headers=saga_session._auth_headers(page),
            timeout=15_000,
        )
        if not response.ok:
            return ""
        text = response.text().strip().strip('"')
        return text
    except Exception:
        return ""


def _fetch_fx_rate(page, *, valuta: str, data: str) -> str:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", "IntrariValuta/GetCursValutar")
    try:
        response = page.request.get(
            f"{absolute}?{urlencode({'Moneda': valuta, 'Data': data})}",
            headers=saga_session._auth_headers(page),
            timeout=15_000,
        )
        if not response.ok:
            return ""
        try:
            body = response.json()
        except Exception:
            return response.text().strip()
        if isinstance(body, (int, float, str)):
            return str(body)
        if isinstance(body, dict):
            for key in ("curs", "Curs", "value", "Value", "data", "Data"):
                if body.get(key) is not None:
                    return str(body.get(key))
        return ""
    except Exception:
        return ""


def _request_setup(*, skip: int = 0, batch_size: int = 50) -> str:
    return json.dumps(
        {
            "FilterSearchType": 1,
            "FilterCaseSensitive": False,
            "FilterCurrentTable": False,
            "Skip": max(skip, 0),
            "BatchSize": max(batch_size, 1),
            "GetRowsCount": True,
        },
        separators=(",", ":"),
    )


def _open_iesiri_valuta(page) -> dict[str, Any]:
    saga_session.clear_capture()
    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", ROUTE)
    current = (page.url or "").casefold()
    if "/sagac/iesirivaluta" in current:
        return {"ok": True, "url": page.url, "via": "current"}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        try:
            page.goto(url, wait_until="commit", timeout=60_000)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Could not open IesiriValuta: {exc}",
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, "saga-iesiri-valuta-missing.png"),
            }
    page.wait_for_timeout(2_000)
    body = ""
    try:
        body = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        pass
    if "iesiri" not in body.casefold() and "valuta" not in body.casefold() and "/iesirivaluta" not in (page.url or "").casefold():
        return {
            "ok": False,
            "error": "Opened a page but IesiriValuta markers were not found.",
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-iesiri-valuta-missing.png"),
        }
    return {"ok": True, "url": page.url, "via": "route"}


def _get_json(page, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", path.lstrip("/"))
    try:
        response = page.request.get(
            f"{absolute}?{urlencode(params or {})}" if params else absolute,
            headers=saga_session._auth_headers(page),
            timeout=45_000,
        )
    except Exception:
        return None
    if not response.ok:
        return {"endpoint": absolute, "status": response.status, "ok": False}
    try:
        body = response.json()
    except Exception:
        return {"endpoint": absolute, "status": response.status, "ok": False, "raw": response.text()[:500]}
    return {"endpoint": absolute, "status": response.status, "ok": True, "body": body}


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "Data", "rows", "Rows", "items", "Items", "result", "Result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            if nested:
                return nested
    return []


def _fetch_header_rows(page, *, skip: int = 0, batch_size: int = 20) -> dict[str, Any]:
    params = {"RequestSetup": _request_setup(skip=skip, batch_size=batch_size)}
    for path in GET_DATA_PATHS:
        probed = _get_json(page, path, params=params)
        if probed and probed.get("ok"):
            rows = _rows_from_payload(probed.get("body"))
            return {**probed, "rows": rows}
    return {"ok": False, "error": "Could not fetch IesiriValuta GetData.", "rows": []}


def _discover_live_schema(page) -> dict[str, Any]:
    info = page.evaluate(
        """() => {
          const out = { hasTable: false };
          const t = (typeof getTable === 'function') ? getTable('IesiriValuta') : null;
          const d = (typeof getTable === 'function') ? getTable('IesiriValutaDetalii') : null;
          out.hasTable = !!t;
          out.hasDetalii = !!d;
          if (t && t.GetVirtualData) {
            const rows = t.GetVirtualData() || [];
            out.headerCount = rows.length;
            out.headerSample = rows[0] || null;
            out.headerKeys = rows[0] ? Object.keys(rows[0]) : [];
          }
          if (d && d.GetVirtualData) {
            const rows = d.GetVirtualData() || [];
            out.lineCount = rows.length;
            out.lineSample = rows[0] || null;
            out.lineKeys = rows[0] ? Object.keys(rows[0]) : [];
          }
          // DOM inputs on add/edit row if present
          const headerInputs = [...document.querySelectorAll(
            '#containerAdvancedTable_IesiriValuta input[class*="rowField"], #tableMain_IesiriValuta input[class*="rowField"]'
          )].map(el => {
            const cls = [...el.classList].find(c => c.startsWith('rowFieldInput_'));
            return cls ? cls.replace('rowFieldInput_', '') : null;
          }).filter(Boolean);
          out.headerInputFields = [...new Set(headerInputs)];
          const lineInputs = [...document.querySelectorAll(
            '#containerAdvancedTable_IesiriValutaDetalii input[class*="rowField"], [id*="IesiriValutaDetalii"] input[class*="rowField"]'
          )].map(el => {
            const cls = [...el.classList].find(c => c.startsWith('rowFieldInput_'));
            return cls ? cls.replace('rowFieldInput_', '') : null;
          }).filter(Boolean);
          out.lineInputFields = [...new Set(lineInputs)];
          return out;
        }"""
    )
    return info if isinstance(info, dict) else {}


def _sender_id(page) -> str:
    try:
        value = page.evaluate(
            "() => (typeof tabID !== 'undefined' && tabID != null) ? String(tabID) : ''"
        )
        if value:
            return str(value)
    except Exception:
        pass
    return "0"


def _coerce_row_json(row_data: dict[str, str]) -> dict[str, Any]:
    """Build RowData object; keep numeric-looking values as numbers when useful."""
    out: dict[str, Any] = {}
    for key, value in row_data.items():
        text = str(value).strip()
        if key in {"TVAI", "Validat"} and text.isdigit():
            out[key] = int(text)
            continue
        if key in {
            "Curs",
            "Cantitate",
            "PretUnitarValuta",
            "PretUnitar",
            "TVA_ART",
            "ValoareValuta",
            "Valoare",
            "TVAValuta",
            "TVA",
            "TotalValuta",
            "Total",
            "NeachitatValuta",
            "Adaos",
        }:
            try:
                out[key] = float(text.replace(",", ".")) if text else text
                continue
            except ValueError:
                pass
        out[key] = text
    # Classic create always sends Id even when empty.
    out.setdefault("Id", row_data.get("Id") or row_data.get("ID_Iesire") or "")
    return out


def _post_rowdata(
    page,
    *,
    path: str,
    row_data: dict[str, str],
    checked: bool = False,
    uvf: Any = None,
) -> dict[str, Any]:
    """POST classic AdvancedControls create/edit using RowData JSON (live-captured for IesiriValuta)."""
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", path.lstrip("/"))
    form: dict[str, str] = {
        "RowData": json.dumps(_coerce_row_json(row_data), ensure_ascii=False, separators=(",", ":")),
        "_CHECKED": "true" if checked else "false",
        "SenderID": _sender_id(page),
        "IsPaste": "false",
    }
    if uvf is None:
        form["uvf"] = ""
    else:
        form["uvf"] = json.dumps(uvf, ensure_ascii=False) if not isinstance(uvf, str) else uvf

    response = page.request.post(
        absolute,
        form=form,
        headers=saga_session._auth_headers(page),
        timeout=60_000,
    )
    content_type = response.headers.get("content-type", "")
    try:
        parsed: Any = response.json() if "json" in content_type else response.text()
    except Exception:
        parsed = response.text()
    return {
        "endpoint": absolute,
        "status": response.status,
        "ok_http": response.ok,
        "request": {"path": path, "row_data": row_data, "checked": checked},
        "response": parsed,
    }


def _post_with_validation_retry(page, *, path: str, row_data: dict[str, str]) -> dict[str, Any]:
    result = _post_rowdata(page, path=path, row_data=row_data, checked=False)
    parsed = result.get("response")

    def _success_payload(resp: Any) -> bool:
        if not isinstance(resp, dict):
            return False
        if resp.get("type") in ("Warning", "Error"):
            return False
        if resp.get("success") is False:
            return False
        status = str(resp.get("status") or "").strip()
        # Classic IesiriValuta create: Validation + numeric status = new row id.
        if resp.get("type") == "Validation" and status.isdigit():
            return True
        if resp.get("success") is True:
            return True
        return False

    # Choice dialogs (e.g. unusual VAT): accept with uvf + _CHECKED.
    if isinstance(parsed, dict) and parsed.get("type") == "Choice":
        flag = str(parsed.get("flagId") or "").strip()
        uvf = [{"FlagId": flag, "Value": "Yes"}] if flag else [{"FlagId": "Choice", "Value": "Yes"}]
        result = _post_rowdata(page, path=path, row_data=row_data, checked=True, uvf=uvf)
        parsed = result.get("response")
        if _success_payload(parsed):
            return {**result, "ok": True}

    # Classic success after first call may be type Validation → confirm with _CHECKED=true.
    if isinstance(parsed, dict) and parsed.get("type") == "Validation":
        if _success_payload(parsed):
            return {**result, "ok": True}
        result = _post_rowdata(page, path=path, row_data=row_data, checked=True)
        parsed = result.get("response")
        if _success_payload(parsed):
            return {**result, "ok": True}
        # "Succes." then numeric id on checked call — already covered; also accept plain Validation
        # without Warning after checked when HTTP ok (some tables return empty-ish payloads).
        if (
            result.get("ok_http")
            and isinstance(parsed, dict)
            and parsed.get("type") == "Validation"
            and not str(parsed.get("status") or "").strip().endswith("?")
            and "Continuam" not in str(parsed.get("status") or "")
        ):
            status = str(parsed.get("status") or "").strip()
            if status.isdigit() or status.casefold().startswith("succes"):
                return {**result, "ok": True}

    if _success_payload(parsed):
        return {**result, "ok": True}

    if isinstance(parsed, dict) and parsed.get("success") is True:
        return {**result, "ok": True}

    # Some creates return empty/row payload with 200 and no Warning.
    if (
        result.get("ok_http")
        and isinstance(parsed, dict)
        and parsed.get("type") not in ("Warning", "Choice", "Error", "Validation")
        and parsed.get("success") is not False
        and "status" not in parsed
    ):
        return {**result, "ok": True}

    return {**result, "ok": False}


def _create_header(page, header: dict[str, str]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for path in CREATE_PATHS:
        result = _post_with_validation_retry(page, path=path, row_data=header)
        attempts.append(result)
        if result.get("ok"):
            return {**result, "attempts": attempts}
    return {"ok": False, "attempts": attempts, "error": "Header create failed on Create_IesiriValuta."}


def _create_line(page, line: dict[str, str]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for path in CREATE_DETAIL_PATHS:
        result = _post_with_validation_retry(page, path=path, row_data=line)
        attempts.append(result)
        if result.get("ok"):
            return {**result, "attempts": attempts}
        # Don't try alternate path when SAGA returned a business Warning/Choice.
        parsed = result.get("response")
        if isinstance(parsed, dict) and parsed.get("type") in ("Warning", "Choice", "Error"):
            break
    return {"ok": False, "attempts": attempts, "error": "Line create failed on Create_IesiriValutaDetalii."}


def _extract_created_ids(response: Any, header: dict[str, str]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key in ("ID_Iesire", "ID_Unic", "OriginalID", "Cod", "NrDoc"):
        if header.get(key):
            ids[key] = header[key]
    if not isinstance(response, dict):
        return ids
    status = str(response.get("status") or "").strip()
    if status.isdigit():
        ids.setdefault("ID_Iesire", status)
    data = response.get("data") or response.get("Data") or {}
    if isinstance(data, dict):
        for key in ("ID_Iesire", "id_Iesire", "idIesire", "ID_Unic", "id_Unic", "OriginalID", "Cod", "NrDoc", "cod", "nrDoc"):
            if data.get(key) is not None and str(data.get(key)).strip():
                canon = {
                    "id_iesire": "ID_Iesire",
                    "idiesire": "ID_Iesire",
                    "id_unic": "ID_Unic",
                    "originalid": "OriginalID",
                    "cod": "Cod",
                    "nrdoc": "NrDoc",
                }.get(_normalize(key).replace(" ", ""), key)
                if canon in ("ID_Iesire", "ID_Unic", "OriginalID", "Cod", "NrDoc"):
                    ids[canon] = str(data.get(key)).strip()
                else:
                    ids[str(key)] = str(data.get(key)).strip()
    return ids


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _fetch_suggested_nr_doc(page, *, data: str, tip: str = "") -> str:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", "IesiriValuta/GetNrIesiriValutaTip")
    try:
        response = page.request.get(
            f"{absolute}?{urlencode({'data': data, 'tip': tip, 'idIesire': '', 'nr_iesire': '', 'isCopyPaste': 'false'})}",
            headers=saga_session._auth_headers(page),
            timeout=15_000,
        )
        if not response.ok:
            return ""
        return response.text().strip().strip('"')
    except Exception:
        return ""


def _prepare_line_amounts(line: dict[str, str], *, curs: str) -> dict[str, str]:
    """Fill RON/FX amount fields when quantity + FX unit price are present."""
    out = dict(line)
    if out.get("Cod_Art") and not out.get("Cod"):
        out["Cod"] = out["Cod_Art"]
    qty = _as_float(out.get("Cantitate"), 1.0) or 1.0
    price_fx = _as_float(out.get("PretUnitarValuta"))
    rate = _as_float(curs, 0.0) or 0.0
    vat = _as_float(out.get("TVA_ART"), 0.0) or 0.0
    if price_fx is not None:
        val_fx = _as_float(out.get("ValoareValuta"), round(qty * price_fx, 2)) or round(qty * price_fx, 2)
        tva_fx = _as_float(out.get("TVAValuta"), round(val_fx * vat / 100.0, 2)) or round(val_fx * vat / 100.0, 2)
        out.setdefault("Cantitate", f"{qty:g}")
        out.setdefault("ValoareValuta", f"{val_fx:.2f}")
        out.setdefault("TVAValuta", f"{tva_fx:.2f}")
        if rate:
            price_ron = _as_float(out.get("PretUnitar"), round(price_fx * rate, 4)) or round(price_fx * rate, 4)
            val_ron = _as_float(out.get("Valoare"), round(val_fx * rate, 2)) or round(val_fx * rate, 2)
            tva_ron = _as_float(out.get("TVA"), round(tva_fx * rate, 2)) or round(tva_fx * rate, 2)
            out.setdefault("PretUnitar", f"{price_ron:.4f}")
            out.setdefault("Valoare", f"{val_ron:.2f}")
            out.setdefault("TVA", f"{tva_ron:.2f}")
    out.setdefault("Adaos", "0.00")
    out.setdefault("UM", out.get("UM") or "BUC")
    return out


def _lines_from_selected_invoice(page, id_iesire: str) -> list[dict[str, Any]]:
    try:
        return page.evaluate(
            """(id) => {
              const t = getTable('IesiriValuta');
              const d = getTable('IesiriValutaDetalii');
              if (!t || !d) return [];
              const rows = t.GetVirtualData ? (t.GetVirtualData() || []) : [];
              const row = rows.find(r => String(r.ID_Iesire) === String(id));
              if (row) {
                try { if (t.SelectRow) t.SelectRow(row); } catch (e) {}
              }
              // Prefer DOM click on NrDoc/ID cell when SelectRow is a no-op.
              return d.GetVirtualData ? (d.GetVirtualData() || []) : [];
            }""",
            id_iesire,
        ) or []
    except Exception:
        return []


def _find_created_invoice(page, header: dict[str, str], ids: dict[str, str]) -> dict[str, Any] | None:
    fetched = _fetch_header_rows(page, skip=0, batch_size=100)
    rows = fetched.get("rows") or []
    want_nr = ids.get("NrDoc") or header.get("NrDoc")
    want_id = ids.get("ID_Iesire")
    for row in rows:
        nr = str(row.get("NrDoc") or row.get("nrDoc") or "")
        id_iesire = str(row.get("ID_Iesire") or row.get("id_Iesire") or "")
        if want_id and _normalize(id_iesire) == _normalize(want_id):
            return row
        if want_nr and _normalize(nr) == _normalize(want_nr):
            return row
    return None


def _ui_create_invoice(page, header: dict[str, str], lines: list[dict[str, str]]) -> dict[str, Any]:
    """Fallback: Adaug header → fill → Salvez, then Adaug each line."""
    filled_header: list[str] = []
    filled_lines: list[list[str]] = []

    def _click_toolbar(table: str, *labels: str) -> bool:
        class_map = {
            "adaug": f".buttonOperationAdd_{table}",
            "salvez": f".buttonOperationSave_{table}",
            "salveaza": f".buttonOperationSave_{table}",
            "anulez": f".buttonOperationCancel_{table}",
        }
        for label in labels:
            cls = class_map.get(label.casefold())
            if cls:
                loc = page.locator(cls)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=5_000)
                        page.wait_for_timeout(700)
                        return True
                    except Exception:
                        pass
            if saga_session._click_if_visible(page, label):
                return True
        try:
            page.evaluate(
                """(table) => {
                  const t = (typeof getTable === 'function') ? getTable(table) : null;
                  if (t && t.ToolbarActionAdd) { t.ToolbarActionAdd(); return 'add'; }
                  return false;
                }""",
                table,
            )
            page.wait_for_timeout(700)
            return True
        except Exception:
            return False

    def _fill(table: str, data: dict[str, str]) -> list[str]:
        filled: list[str] = []
        for field, value in data.items():
            selectors = [
                f".rowFieldInput_{field}",
                f"#containerAdvancedTable_{table} .rowFieldInput_{field}",
                f"input.rowFieldInput_{field}",
                f"textarea.rowFieldInput_{field}",
            ]
            for selector in selectors:
                loc = page.locator(selector)
                if loc.count() == 0:
                    continue
                try:
                    target = loc.last
                    target.click(timeout=2_000)
                    target.fill("")
                    target.type(value, delay=10)
                    filled.append(field)
                    break
                except Exception:
                    continue
            # combo spans
            if field not in filled:
                try:
                    ok = page.evaluate(
                        """({table, field, value}) => {
                          const row = document.querySelector(
                            `#containerAdvancedTable_${table} .selectedRow_Dark, #containerAdvancedTable_${table} .selectedRow_Light`
                          ) || document.querySelector(`#containerAdvancedTable_${table} tr`);
                          if (!row) return false;
                          const toggle = row.querySelector(`[id*="dropdownToggle"][id*="${field}"], #dropdownToggle_${field}`);
                          if (!toggle) return false;
                          toggle.click();
                          return true;
                        }""",
                        {"table": table, "field": field, "value": value},
                    )
                    if ok:
                        page.wait_for_timeout(300)
                        opt = page.get_by_text(value, exact=False)
                        if opt.count() > 0:
                            opt.first.click(timeout=2_000)
                            filled.append(field)
                except Exception:
                    pass
        return filled

    if not _click_toolbar("IesiriValuta", "Adaug", "Adauga", "Adaugă", "Add"):
        return {"ok": False, "error": "Could not start IesiriValuta add mode."}
    filled_header = _fill("IesiriValuta", header)
    if not _click_toolbar("IesiriValuta", "Salvez", "Salveaza", "Salvează", "Save"):
        return {"ok": False, "error": "Could not save IesiriValuta header.", "filled_header": filled_header}
    page.wait_for_timeout(1_200)
    for label in ("Da", "Yes"):
        if saga_session._click_if_visible(page, label):
            page.wait_for_timeout(800)
            break

    for line in lines:
        if not _click_toolbar("IesiriValutaDetalii", "Adaug", "Adauga", "Adaugă", "Add"):
            return {
                "ok": False,
                "error": "Header may be saved but could not add detail line.",
                "filled_header": filled_header,
                "filled_lines": filled_lines,
            }
        filled_lines.append(_fill("IesiriValutaDetalii", line))
        if not _click_toolbar("IesiriValutaDetalii", "Salvez", "Salveaza", "Salvează", "Save"):
            return {
                "ok": False,
                "error": "Could not save a detail line.",
                "filled_header": filled_header,
                "filled_lines": filled_lines,
            }
        page.wait_for_timeout(900)
        for label in ("Da", "Yes"):
            if saga_session._click_if_visible(page, label):
                page.wait_for_timeout(600)
                break

    return {
        "ok": True,
        "via": "ui",
        "filled_header": filled_header,
        "filled_lines": filled_lines,
    }


def create_fx_invoice(
    header: dict[str, Any],
    lines: list[dict[str, Any]] | None = None,
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    raw_header = {str(k): v for k, v in (header or {}).items() if v is not None and str(v).strip() != ""}
    raw_lines = []
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        cleaned = {str(k): v for k, v in line.items() if v is not None and str(v).strip() != ""}
        if cleaned:
            raw_lines.append(cleaned)

    if not raw_header:
        return {
            "ok": False,
            "error": "header cannot be empty.",
            "writable_fields": fx_invoice_field_catalog(),
        }
    if not raw_lines:
        return {
            "ok": False,
            "error": "lines cannot be empty — provide at least one invoice line.",
            "writable_fields": fx_invoice_field_catalog(),
        }

    mapped_header, unknown_header = _map_fields(raw_header, HEADER_FIELD_CATALOG)
    if unknown_header:
        return {
            "ok": False,
            "error": f"Unknown header field(s): {', '.join(unknown_header)}",
            "unknown_fields": unknown_header,
            "writable_fields": fx_invoice_field_catalog()["header_fields"],
        }

    mapped_lines: list[dict[str, str]] = []
    unknown_line_fields: list[str] = []
    for idx, line in enumerate(raw_lines):
        mapped, unknown = _map_fields(line, LINE_FIELD_CATALOG)
        if unknown:
            unknown_line_fields.append(f"line[{idx}]: {', '.join(unknown)}")
        if not mapped:
            return {"ok": False, "error": f"line[{idx}] has no recognizable fields after mapping."}
        mapped_lines.append(mapped)
    if unknown_line_fields:
        return {
            "ok": False,
            "error": "Unknown line field(s): " + "; ".join(unknown_line_fields),
            "writable_fields": fx_invoice_field_catalog()["line_fields"],
        }

    missing_line_cont = [idx for idx, line in enumerate(mapped_lines) if not line.get("Cont")]
    if missing_line_cont:
        return {
            "ok": False,
            "error": (
                "Each line requires Cont (revenue account), e.g. 704 or 707. "
                f"Missing on line index(es): {missing_line_cont}."
            ),
            "writable_fields": fx_invoice_field_catalog()["line_fields"],
        }

    # Minimal required set for a usable FX invoice.
    missing = []
    if "Client" not in mapped_header and "Cod" not in mapped_header:
        missing.append("Client or Cod")
    if "Valuta" not in mapped_header:
        missing.append("Valuta")
    if "Data" not in mapped_header:
        missing.append("Data")
    if missing:
        return {
            "ok": False,
            "error": "Missing required header field(s): " + ", ".join(missing),
            "mapped_header": mapped_header,
        }

    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "create_fx_invoice",
            "preview": {"header": raw_header, "lines": raw_lines},
            "mapped": {"header": mapped_header, "lines": mapped_lines},
            "details": (
                "Preview only — will create an IesiriValuta (FX sales) invoice with these "
                "user-specified fields only. Confirm then call with confirm_write=true."
            ),
            "writable_fields": fx_invoice_field_catalog(),
        }

    def _run(browser_page):
        p = _ready(browser_page)
        header_data = _resolve_client(p, dict(mapped_header))
        opened = _open_iesiri_valuta(p)
        if not opened.get("ok"):
            return {"ok": False, **opened}

        saga_session.clear_capture()
        # Tip '' = Factura; only auto-fill when SAGA returns a most-used tip.
        if "Tip" not in header_data:
            tip = _fetch_tip_factura(p, header_data.get("Data") or "")
            header_data["Tip"] = tip or ""
        if header_data.get("Valuta") and header_data.get("Data") and not header_data.get("Curs"):
            curs = _fetch_fx_rate(p, valuta=header_data["Valuta"], data=header_data["Data"])
            if curs:
                header_data["Curs"] = curs
        if not header_data.get("NrDoc") and header_data.get("Data"):
            suggested = _fetch_suggested_nr_doc(
                p, data=header_data["Data"], tip=header_data.get("Tip") or ""
            )
            if suggested:
                header_data["NrDoc"] = suggested

        header_data.setdefault("TVAI", "0")
        header_data.setdefault("Validat", "0")
        for amount_key in (
            "ValoareValuta",
            "Valoare",
            "TVAValuta",
            "TVA",
            "TotalValuta",
            "Total",
            "NeachitatValuta",
            "Adaos",
        ):
            header_data.setdefault(amount_key, "0.00")

        prepared_lines = [
            _prepare_line_amounts(line, curs=header_data.get("Curs") or "0") for line in mapped_lines
        ]

        header_result = _create_header(p, header_data)
        ids = _extract_created_ids(
            (header_result.get("response") if header_result.get("ok") else None),
            header_data,
        )
        if header_result.get("ok") and not ids.get("ID_Iesire"):
            # Fallback: locate by NrDoc after create.
            found = _find_created_invoice(p, header_data, ids)
            if found and found.get("ID_Iesire"):
                ids["ID_Iesire"] = str(found["ID_Iesire"])

        line_results: list[dict[str, Any]] = []
        if header_result.get("ok") and ids.get("ID_Iesire"):
            for line in prepared_lines:
                linked = dict(line)
                linked["ID_Iesire"] = ids["ID_Iesire"]
                line_results.append(_create_line(p, linked))
        elif header_result.get("ok"):
            return {
                "ok": False,
                "created": False,
                "via": "api",
                "error": "Header created but ID_Iesire was not returned; lines were not added.",
                "header": header_data,
                "ids": ids,
                "header_result": {
                    "endpoint": header_result.get("endpoint"),
                    "response": header_result.get("response"),
                },
                "url": p.url,
                "screenshot_path": saga_session._save_screenshot(p, "saga-fx-invoice-create-failed.png"),
                "capture_path": saga_session._dump_capture("network-fx-invoice-create.json"),
            }

        all_lines_ok = bool(line_results) and all(r.get("ok") for r in line_results)
        verified = _find_created_invoice(p, header_data, ids) if header_result.get("ok") else None
        detail_lines: list[dict[str, Any]] = []
        if ids.get("ID_Iesire"):
            # Click/select so detail virtual data refreshes for verification.
            try:
                p.evaluate(
                    """(id) => {
                      const t = getTable('IesiriValuta');
                      const rows = (t && t.GetVirtualData) ? (t.GetVirtualData() || []) : [];
                      const row = rows.find(r => String(r.ID_Iesire) === String(id));
                      if (row) {
                        try { if (t.SelectRow) t.SelectRow(row); } catch (e) {}
                      }
                      const cells = [...document.querySelectorAll(
                        '#containerAdvancedTable_IesiriValuta tr, #tableMain_IesiriValuta tr'
                      )];
                      for (const tr of cells) {
                        const text = tr.textContent || '';
                        // Match id cell when present; AdvancedControls often keeps ID in a hidden field.
                        const idInput = tr.querySelector('.rowFieldInput_ID_Iesire, input[class*="ID_Iesire"]');
                        if (idInput && String(idInput.value) === String(id)) {
                          tr.click();
                          return 'input';
                        }
                      }
                      if (row && row.NrDoc) {
                        const td = [...document.querySelectorAll(
                          '#containerAdvancedTable_IesiriValuta td, #tableMain_IesiriValuta td'
                        )].find(el => (el.textContent || '').trim() === String(row.NrDoc));
                        if (td) { td.click(); return 'nrdoc'; }
                      }
                      return row ? 'selected' : 'miss';
                    }""",
                    ids["ID_Iesire"],
                )
                p.wait_for_timeout(1_000)
            except Exception:
                pass
            detail_lines = [
                line
                for line in (_lines_from_selected_invoice(p, ids["ID_Iesire"]) or [])
                if str(line.get("ID_Iesire") or "") == str(ids["ID_Iesire"])
            ]

        if header_result.get("ok") and all_lines_ok:
            return {
                "ok": True,
                "created": True,
                "via": "api",
                "header": header_data,
                "lines": prepared_lines,
                "ids": ids,
                "invoice": verified,
                "detail_lines": detail_lines,
                "header_result": {
                    "endpoint": header_result.get("endpoint"),
                    "response": header_result.get("response"),
                },
                "line_results": [
                    {"endpoint": r.get("endpoint"), "response": r.get("response"), "ok": r.get("ok")}
                    for r in line_results
                ],
                "url": p.url,
                "screenshot_path": saga_session._save_screenshot(p, "saga-fx-invoice-created.png"),
                "capture_path": saga_session._dump_capture("network-fx-invoice-create.json"),
            }

        # No slow UI fallback — return API diagnostics so the agent can fix fields.
        api_error = None
        if not header_result.get("ok"):
            resp = header_result.get("response") or (header_result.get("attempts") or [{}])[-1].get("response")
            api_error = (
                (resp.get("status") if isinstance(resp, dict) else None)
                or header_result.get("error")
                or "Header create failed."
            )
        elif not all_lines_ok:
            failed = next((r for r in line_results if not r.get("ok")), None)
            resp = (failed or {}).get("response")
            api_error = (
                (resp.get("status") if isinstance(resp, dict) else None)
                or (failed or {}).get("error")
                or "One or more lines failed."
            )

        return {
            "ok": False,
            "created": False,
            "via": "api",
            "header": header_data,
            "lines": prepared_lines,
            "ids": ids,
            "invoice": verified,
            "detail_lines": detail_lines,
            "api_header_result": {
                "ok": header_result.get("ok"),
                "endpoint": header_result.get("endpoint"),
                "response": header_result.get("response")
                or (header_result.get("attempts") or [{}])[-1].get("response"),
            },
            "api_line_results": [
                {"ok": r.get("ok"), "endpoint": r.get("endpoint"), "response": r.get("response")}
                for r in line_results
            ],
            "url": p.url,
            "screenshot_path": saga_session._save_screenshot(p, "saga-fx-invoice-create-failed.png"),
            "capture_path": saga_session._dump_capture("network-fx-invoice-create.json"),
            "error": api_error or "Could not create FX invoice via API.",
        }

    return saga_session.run_in_session(_run)



def probe_fx_invoice_screen() -> dict[str, Any]:
    """Read-only discovery helper for IesiriValuta endpoints/fields."""

    def _run(browser_page):
        p = _ready(browser_page)
        opened = _open_iesiri_valuta(p)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        schema = _discover_live_schema(p)
        # Enter add mode briefly to expose full header/line field sets, then cancel.
        try:
            p.evaluate(
                """() => {
                  const t = getTable('IesiriValuta');
                  if (t && t.ToolbarActionAdd) t.ToolbarActionAdd();
                }"""
            )
            p.wait_for_timeout(800)
            schema_add = _discover_live_schema(p)
            p.evaluate(
                """() => {
                  const t = getTable('IesiriValuta');
                  if (t && t.ToolbarActionCancel) t.ToolbarActionCancel();
                }"""
            )
            p.wait_for_timeout(400)
        except Exception:
            schema_add = {}
        headers = _fetch_header_rows(p, skip=0, batch_size=3)
        tip_options = None
        try:
            tip_resp = p.request.get(
                urljoin(saga_session.app_base_url(p).rstrip("/") + "/", "IesiriValuta/GetData_ComboBox_Tip_Iesiri")
                + "?Filter=",
                headers=saga_session._auth_headers(p),
                timeout=15_000,
            )
            tip_options = tip_resp.json() if tip_resp.ok else tip_resp.text()[:300]
        except Exception as exc:
            tip_options = {"error": str(exc)}
        return {
            "ok": True,
            "url": p.url,
            "schema": schema,
            "schema_add_mode": schema_add,
            "get_data": {
                "endpoint": headers.get("endpoint"),
                "status": headers.get("status"),
                "row_count": len(headers.get("rows") or []),
                "sample": (headers.get("rows") or [None])[0],
                "sample_keys": sorted(((headers.get("rows") or [{}])[0] or {}).keys()),
            },
            "tip_options": tip_options,
            "create_contract": {
                "endpoint": "IesiriValuta/Create_IesiriValuta",
                "form": ["RowData(JSON)", "_CHECKED", "SenderID", "IsPaste", "uvf"],
            },
            "catalog": fx_invoice_field_catalog(),
            "screenshot_path": saga_session._save_screenshot(p, "saga-iesiri-valuta-probe.png"),
            "capture_path": saga_session._dump_capture("network-iesiri-valuta-probe.json"),
        }

    return saga_session.run_in_session(_run)
