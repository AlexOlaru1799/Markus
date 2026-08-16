from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urljoin

from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import schema as saga_schema
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


def fx_invoice_field_catalog() -> dict[str, Any]:
    described = saga_schema.describe_screen("iesiri_valuta")
    catalog = saga_schema.catalog_for("iesiri_valuta")
    return {
        "ok": True,
        "screen": "IesiriValuta",
        "url": described.get("url"),
        "header_fields": described.get("header_fields") or described.get("fields") or [],
        "line_fields": described.get("line_fields") or [],
        "usage": catalog.get("usage")
        or {
            "header": "Required: Client or Cod, Valuta, Data. Optional: Scadent, NrDoc, Tip, Curs, Agent, notes.",
            "lines": (
                "Required per line: Cont, and amounts (Cantitate + PretUnitarValuta, or explicit totals). "
                "Also useful: Denumire, Cod_Art/Cod, UM, TVA_ART, Gestiune."
            ),
            "confirm_write": "Call saga_add_iesiri_valuta with confirm_write=false first, then true after user OK.",
            "endpoint": "POST IesiriValuta/Create_IesiriValuta (+ Create_IesiriValutaDetalii) with RowData JSON.",
        },
        "notes": list(catalog.get("notes") or described.get("notes") or []),
    }


def _map_fields(payload: dict[str, Any], operation: str) -> tuple[dict[str, str], list[str]]:
    mapped = saga_schema.map_fields(operation, payload)
    return mapped.fields, mapped.unknown


def _ready(page):
    from markus_mcp.tools.saga import partners as saga_partners

    return saga_partners._ready(page)


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


def _rate_from_body(body: Any) -> str:
    if isinstance(body, (int, float)):
        return str(body)
    if isinstance(body, str) and body.strip():
        return body.strip().strip('"')
    if isinstance(body, dict):
        for key in ("curs", "Curs", "value", "Value", "data", "Data", "status", "Status"):
            if body.get(key) not in (None, ""):
                return str(body.get(key)).strip()
    return ""


def fetch_last_valuta(page, *, valuta: str, data: str) -> str:
    """Registru casă valută rate; falls back to GetCursValutar."""
    params = {"Moneda": valuta, "Valuta": valuta, "Data": data, "data": data}
    for path in (
        "RegistruCasaValuta/GetLastValuta",
        "RegistruCasa/GetLastValuta",
        "Home/GetLastValuta",
    ):
        probed = saga_protocol.get_json(page, path, params=params)
        if not probed or not probed.get("ok"):
            continue
        rate = _rate_from_body(probed.get("body"))
        if rate:
            return rate
    return _fetch_fx_rate(page, valuta=valuta, data=data)


def _request_setup(*, skip: int = 0, batch_size: int = 50, **kwargs: Any) -> str:
    return saga_protocol.request_setup(skip=skip, batch_size=batch_size, **kwargs)


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
    return saga_protocol.get_json(page, path, params=params)


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    return saga_protocol.rows_from_payload(payload)


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


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


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


def create_fx_invoice(
    header: dict[str, Any],
    lines: list[dict[str, Any]] | None = None,
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Named FX MCP entry. Mapping/preview/post share invoices._add / post_on_page."""
    from markus_mcp.tools.saga import invoices as saga_invoices

    result = saga_invoices._add(
        ron_operation="iesiri_valuta",
        fx_operation="iesiri_valuta",
        header=header,
        lines=lines,
        document=None,
        confirm_write=confirm_write,
        action="create_fx_invoice",
    )
    if result.get("requires_confirmation") or not result.get("ok"):
        result.setdefault("writable_fields", fx_invoice_field_catalog())
    return result


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
