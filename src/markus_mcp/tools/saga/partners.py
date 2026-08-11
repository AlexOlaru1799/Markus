from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode, urljoin

from markus_mcp.tools.saga import session as saga_session


PARTNER_ROUTE_CANDIDATES = (
    "/Clienti",
    "/Furnizori",
    "/Parteneri",
    "/Parteneri/Index",
    "/Terti",
    "/Nomenclatoare/Parteneri",
)

PARTNER_DATA_CANDIDATES = (
    "/Clienti/GetData_Clienti",
    "/Furnizori/GetData_Furnizori",
    "/Parteneri/GetData",
    "/Parteneri/List",
    "/Clienti/GetData",
)


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().split()).casefold()


def _save_partner_capture(page, name: str) -> str:
    return saga_session._save_screenshot(page, name)


def _safe_goto(page, url: str) -> bool:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        return True
    except Exception:
        try:
            page.goto(url, wait_until="commit", timeout=60_000)
            return True
        except Exception:
            return False


def _partner_bases(page) -> list[str]:
    bases = [saga_session.app_base_url(page), saga_session.BASE_URL]
    # Deduplicate while preserving order.
    out: list[str] = []
    for base in bases:
        if base and base not in out:
            out.append(base)
    return out


def _open_partners_ui(page) -> dict[str, Any]:
    saga_session.clear_capture()
    tried: list[str] = []

    # Already on clients screen in the firm app.
    current = (page.url or "").casefold()
    if "/sagac/clienti" in current:
        return {"ok": True, "url": page.url, "via": "current", "tried": tried}

    for base in _partner_bases(page):
        for route in PARTNER_ROUTE_CANDIDATES:
            url = urljoin(base.rstrip("/") + "/", route.lstrip("/"))
            tried.append(url)
            if not _safe_goto(page, url):
                continue
            page.wait_for_timeout(1_500)
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=3_000)
            except Exception:
                pass
            markers = ("partener", "client", "cui", "denumire", "cod fiscal", "adaug", "modific")
            if any(token in body.casefold() for token in markers) or "/clienti" in (page.url or "").casefold():
                return {"ok": True, "url": page.url, "via": "route", "tried": tried}

    for label in ("Clienti", "Clienți", "Parteneri", "Nomenclatoare", "Furnizori"):
        loc = page.get_by_text(label, exact=False)
        if loc.count() == 0:
            continue
        try:
            loc.first.click(timeout=3_000)
            page.wait_for_timeout(1_500)
            tried.append(f"click:{label}")
            body = page.locator("body").inner_text(timeout=3_000)
            if any(token in body.casefold() for token in ("client", "partener", "cui", "denumire")):
                return {"ok": True, "url": page.url, "via": f"menu:{label}", "tried": tried}
        except Exception:
            continue

    return {
        "ok": False,
        "url": page.url,
        "tried": tried,
        "screenshot_path": _save_partner_capture(page, "saga-partners-missing.png"),
        "error": "Could not open partners/clients screen.",
    }


def _request_setup(*, skip: int = 0, batch_size: int = 100) -> str:
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


def _fetch_clienti_data(page, *, skip: int = 0, batch_size: int = 100) -> dict[str, Any] | None:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", "Clienti/GetData_Clienti")
    params = {"RequestSetup": _request_setup(skip=skip, batch_size=batch_size)}
    try:
        response = page.request.get(
            f"{absolute}?{urlencode(params)}",
            headers=saga_session._auth_headers(page),
            timeout=30_000,
        )
    except Exception:
        return None
    if not response.ok:
        return None
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, (dict, list)):
        return {"endpoint": absolute, "params": params, "body": body, "status": response.status}
    return None


def _probe_data_endpoints(page, query: str | None = None) -> dict[str, Any] | None:
    # Prefer the real SAGA C clients endpoint discovered after firm connect.
    fetched = _fetch_clienti_data(page, skip=0, batch_size=100)
    if fetched is not None:
        return fetched

    token_headers = saga_session._auth_headers(page)
    for base in _partner_bases(page):
        for path in PARTNER_DATA_CANDIDATES:
            absolute = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
            try:
                response = page.request.get(
                    absolute,
                    params={
                        "RequestSetup": _request_setup(skip=0, batch_size=100),
                        "page": 1,
                        "pageSize": 50,
                        "q": query or "",
                    },
                    headers=token_headers,
                    timeout=30_000,
                )
            except Exception:
                continue
            if not response.ok:
                continue
            content_type = response.headers.get("content-type", "")
            try:
                body = response.json() if "json" in content_type or content_type.endswith("+json") else None
            except Exception:
                body = None
            if isinstance(body, (dict, list)):
                return {"endpoint": absolute, "body": body, "status": response.status}
    return None


def _rows_from_json(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "Data", "rows", "Rows", "items", "Items", "result", "Result", "parteneri", "Parteneri"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _rows_from_json(value)
            if nested:
                return nested
    return []


def _scrape_partner_table(page) -> list[dict[str, Any]]:
    partners: list[dict[str, Any]] = []
    tables = page.locator("table")
    count = tables.count()
    for t_index in range(count):
        table = tables.nth(t_index)
        headers = [h.strip() for h in table.locator("thead th").all_inner_texts()] if table.locator("thead th").count() else []
        rows = table.locator("tbody tr")
        row_count = rows.count()
        if row_count == 0:
            continue
        for r_index in range(min(row_count, 200)):
            row = rows.nth(r_index)
            cells = [c.strip() for c in row.locator("td").all_inner_texts()]
            if not cells or all(not c for c in cells):
                continue
            item: dict[str, Any] = {"row_index": r_index, "cells": cells}
            if headers:
                for header, cell in zip(headers, cells):
                    if header:
                        item[header] = cell
            # Common positional mapping fallback.
            if len(cells) >= 2:
                item.setdefault("cod", cells[0])
                item.setdefault("denumire", cells[1])
            if len(cells) >= 3:
                item.setdefault("cui", cells[2])
            partners.append(item)
        if partners:
            break
    return partners


def _filter_partners(partners: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    if not query:
        return partners
    needle = _normalize(query)
    filtered: list[dict[str, Any]] = []
    for partner in partners:
        blob = _normalize(json.dumps(partner, ensure_ascii=False))
        if needle in blob:
            filtered.append(partner)
    return filtered


def _partner_id(partner: dict[str, Any]) -> str | None:
    for key in ("id", "Id", "ID", "cod", "Cod", "COD", "cui", "CUI"):
        value = partner.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    cells = partner.get("cells")
    if isinstance(cells, list) and cells:
        return str(cells[0]).strip()
    return None


def _ensure_partners_context(page) -> dict[str, Any]:
    opened = _open_partners_ui(page)
    if not opened.get("ok"):
        return opened
    probed = _probe_data_endpoints(page)
    partners = _rows_from_json((probed or {}).get("body")) if probed else []
    source = "api" if partners else "ui"
    if not partners:
        partners = _scrape_partner_table(page)
    return {
        "ok": True,
        "url": page.url,
        "source": source,
        "endpoint": (probed or {}).get("endpoint"),
        "partners": partners,
        "opened": opened,
        "capture_path": saga_session._dump_capture("network-partners.json"),
        "screenshot_path": _save_partner_capture(page, "saga-partners.png"),
    }


def _ready(page):
    # ensure_ready_page already opens browser on worker; when called via run_in_session
    # we still enforce auth state here.
    state = saga_session._detect_state(page)
    if state.needs_otp:
        raise RuntimeError("SAGA OTP required. Call saga_submit_otp with the 6-digit email code.")
    if not state.logged_in:
        saga_session._login_impl()
        page = saga_session._ensure_browser()
        state = saga_session._detect_state(page)
    if state.needs_otp:
        raise RuntimeError("SAGA OTP required. Call saga_submit_otp with the 6-digit email code.")
    if not state.logged_in:
        raise RuntimeError("Not logged in to SAGA WEB. Call saga_login first.")
    if state.firm_selected:
        return page
    if "/firme" in (page.url or "").casefold() or not state.firm_selected:
        if "/firme" not in (page.url or "").casefold() and "web2.sagasoft.ro" not in (page.url or "").casefold():
            try:
                page.goto(f"{saga_session.BASE_URL}/Firme", wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                pass
        if "/firme" in (page.url or "").casefold():
            saga_session._select_firm_if_needed(page)
            page.wait_for_timeout(2_000)
        state = saga_session._detect_state(page)
        if not state.firm_selected:
            raise RuntimeError(
                "Logged in but no firm connected. Open /Firme, select a firm, click Conectare, then retry."
            )
    return page


def list_partners(*, page: int = 1, page_size: int = 50, query: str | None = None) -> dict[str, Any]:
    def _run(browser_page):
        p = _ready(browser_page)
        ctx = _ensure_partners_context(p)
        if not ctx.get("ok"):
            return {"ok": False, **ctx}
        partners = _filter_partners(list(ctx.get("partners") or []), query)
        start = max(page - 1, 0) * max(page_size, 1)
        end = start + max(page_size, 1)
        slice_ = partners[start:end]
        return {
            "ok": True,
            "page": page,
            "page_size": page_size,
            "total": len(partners),
            "count": len(slice_),
            "source": ctx.get("source"),
            "endpoint": ctx.get("endpoint"),
            "url": ctx.get("url"),
            "partners": slice_,
            "screenshot_path": ctx.get("screenshot_path"),
        }

    return saga_session.run_in_session(_run)


def search_partners(query: str, *, limit: int = 50) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query cannot be empty."}

    def _run(browser_page):
        p = _ready(browser_page)
        opened = _open_partners_ui(p)
        if not opened.get("ok"):
            return {"ok": False, **opened}

        # Prefer in-page search box when present.
        search_box = p.locator(
            'input[type="search"], input[placeholder*="Caut" i], input[placeholder*="Search" i], input[name*="search" i]'
        )
        if search_box.count() > 0:
            try:
                search_box.first.fill("")
                search_box.first.type(q, delay=20)
                search_box.first.press("Enter")
                p.wait_for_timeout(1_500)
            except Exception:
                pass

        probed = _probe_data_endpoints(p, query=q)
        partners = _rows_from_json((probed or {}).get("body")) if probed else []
        source = "api" if partners else "ui"
        if not partners:
            partners = _scrape_partner_table(p)
        partners = _filter_partners(partners, q)[: max(limit, 1)]
        return {
            "ok": True,
            "query": q,
            "count": len(partners),
            "source": source,
            "endpoint": (probed or {}).get("endpoint"),
            "url": p.url,
            "partners": partners,
            "screenshot_path": _save_partner_capture(p, "saga-partners-search.png"),
            "capture_path": saga_session._dump_capture("network-partners-search.json"),
        }

    return saga_session.run_in_session(_run)


def get_partner(partner_id: str) -> dict[str, Any]:
    key = (partner_id or "").strip()
    if not key:
        return {"ok": False, "error": "partner_id cannot be empty."}

    result = search_partners(key, limit=50)
    if not result.get("ok"):
        return result
    exact: list[dict[str, Any]] = []
    for partner in result.get("partners") or []:
        pid = _partner_id(partner)
        den = str(partner.get("denumire") or partner.get("Denumire") or "")
        if _normalize(pid or "") == _normalize(key) or _normalize(den) == _normalize(key):
            exact.append(partner)
    if not exact:
        return {
            "ok": False,
            "error": f"No exact partner match for '{key}'.",
            "candidates": result.get("partners") or [],
        }
    if len(exact) > 1:
        return {
            "ok": False,
            "error": f"Multiple exact matches for '{key}'.",
            "matches": exact,
        }
    return {"ok": True, "partner": exact[0], "url": result.get("url")}


# Writable SAGA Clienti columns. Agents may use either the SAGA name or an alias.
# Only keys provided by the user are written; unspecified fields are left untouched.
CLIENTI_FIELD_CATALOG: dict[str, dict[str, Any]] = {
    "Cod": {"aliases": ("cod",), "kind": "text", "description": "Client code"},
    "Denumire": {
        "aliases": ("denumire", "name", "company_name"),
        "kind": "text",
        "description": "Client name (required on create)",
        "required_on_create": True,
    },
    "CodFiscal": {
        "aliases": ("cod_fiscal", "codfiscal", "cui", "cnp"),
        "kind": "text",
        "description": "Fiscal code / CNP",
    },
    "Analitic": {"aliases": ("analitic", "cont_analitic"), "kind": "text", "description": "Analytical account"},
    "Tara": {"aliases": ("tara", "country"), "kind": "combo", "description": "Country code (e.g. RO)"},
    "Judet": {"aliases": ("judet", "county"), "kind": "combo", "description": "County code (e.g. B)"},
    "Localitate": {"aliases": ("localitate", "city"), "kind": "combo", "description": "City / locality"},
    "Adresa": {"aliases": ("adresa", "address"), "kind": "text", "description": "Street address"},
    "ContBanca": {"aliases": ("cont_banca", "iban", "bank_account"), "kind": "text", "description": "Bank account"},
    "Banca": {"aliases": ("banca", "bank"), "kind": "text", "description": "Bank name"},
    "Telefon": {"aliases": ("telefon", "phone"), "kind": "text", "description": "Phone"},
    "Email": {"aliases": ("email", "mail"), "kind": "text", "description": "Email"},
    "Grupa": {"aliases": ("grupa", "group"), "kind": "text", "description": "Client group"},
    "REG_COM": {"aliases": ("reg_com", "registru_comert", "j"), "kind": "text", "description": "Trade register"},
    "Delegat": {"aliases": ("delegat",), "kind": "text", "description": "Delegate name"},
    "BI_SERIE": {"aliases": ("bi_serie",), "kind": "text", "description": "ID card series"},
    "BI_NUMAR": {"aliases": ("bi_numar",), "kind": "text", "description": "ID card number"},
    "BI_POL": {"aliases": ("bi_pol",), "kind": "text", "description": "ID card issuer"},
    "MASINA": {"aliases": ("masina", "auto"), "kind": "text", "description": "Vehicle"},
    "AGENT": {"aliases": ("agent",), "kind": "text", "description": "Agent code"},
    "DEN_AGENT": {"aliases": ("den_agent", "agent_name"), "kind": "text", "description": "Agent name"},
    "Discount": {"aliases": ("discount",), "kind": "text", "description": "Discount"},
    "ZileScadenta": {
        "aliases": ("zile_scadenta", "scadenta", "due_days"),
        "kind": "text",
        "description": "Payment due days",
    },
    "C_LIMIT": {
        "aliases": ("c_limit", "limita_sold", "credit_limit"),
        "kind": "text",
        "description": "Credit limit",
    },
    "BLOCAT": {"aliases": ("blocat", "blocked"), "kind": "text", "description": "Blocked flag 0/1"},
    "InformatiiSuplimentare": {
        "aliases": ("informatii_suplimentare", "notes", "info"),
        "kind": "text",
        "description": "Extra notes",
    },
    "TIP_TERT": {"aliases": ("tip_tert",), "kind": "text", "description": "Partner type (I/E/empty)"},
    "IsTVA": {"aliases": ("is_tva", "tva"), "kind": "text", "description": "VAT payer 0/1"},
    "DATA_V_TVA": {"aliases": ("data_v_tva",), "kind": "text", "description": "VAT date"},
    "IsEFactura": {"aliases": ("is_efactura", "efactura"), "kind": "text", "description": "e-Factura 0/1"},
    "ID_EFACT": {"aliases": ("id_efact",), "kind": "text", "description": "e-Factura id"},
}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {}
for _saga_name, _meta in CLIENTI_FIELD_CATALOG.items():
    FIELD_ALIASES[_normalize(_saga_name)] = (_saga_name,)
    for _alias in _meta.get("aliases") or ():
        FIELD_ALIASES[_normalize(str(_alias))] = (_saga_name,)

JUDET_CODES = {
    "bucuresti": "B",
    "bucurești": "B",
    "alba": "AB",
    "arges": "AG",
    "argeș": "AG",
    "arad": "AR",
    "bacau": "BC",
    "bacău": "BC",
    "bihor": "BH",
    "bistrita-nasaud": "BN",
    "bistrița-năsăud": "BN",
    "braila": "BR",
    "brăila": "BR",
    "brasov": "BV",
    "brașov": "BV",
    "buzau": "BZ",
    "buzău": "BZ",
    "calarasi": "CL",
    "călărași": "CL",
    "caras-severin": "CS",
    "caraș-severin": "CS",
    "cluj": "CJ",
    "constanta": "CT",
    "constanța": "CT",
    "covasna": "CV",
    "dambovita": "DB",
    "dâmbovița": "DB",
    "dolj": "DJ",
    "galati": "GL",
    "galați": "GL",
    "giurgiu": "GR",
    "gorj": "GJ",
    "harghita": "HR",
    "hunedoara": "HD",
    "ialomita": "IL",
    "ialomița": "IL",
    "iasi": "IS",
    "iași": "IS",
    "ilfov": "IF",
    "maramures": "MM",
    "maramureș": "MM",
    "mehedinti": "MH",
    "mehedinți": "MH",
    "mures": "MS",
    "mureș": "MS",
    "neamt": "NT",
    "neamț": "NT",
    "olt": "OT",
    "prahova": "PH",
    "salaj": "SJ",
    "sălaj": "SJ",
    "satu mare": "SM",
    "sibiu": "SB",
    "suceava": "SV",
    "teleorman": "TR",
    "timis": "TM",
    "timiș": "TM",
    "tulcea": "TL",
    "valcea": "VL",
    "vâlcea": "VL",
    "vaslui": "VS",
    "vrancea": "VN",
}


def partner_field_catalog() -> dict[str, Any]:
    fields = []
    for name, meta in CLIENTI_FIELD_CATALOG.items():
        fields.append(
            {
                "name": name,
                "aliases": list(meta.get("aliases") or ()),
                "kind": meta.get("kind"),
                "description": meta.get("description"),
                "required_on_create": bool(meta.get("required_on_create")),
            }
        )
    return {
        "ok": True,
        "count": len(fields),
        "fields": fields,
        "details": (
            "Pass only the fields the user specifies. Unspecified fields are left unchanged "
            "(update) or blank (create). Use either the SAGA name or an alias as the dict key."
        ),
    }


def _normalize_cui(value: str) -> str:
    text_value = (value or "").strip().upper().replace(" ", "")
    if text_value.startswith("RO"):
        text_value = text_value[2:]
    return text_value


def _is_valid_ro_cui(value: str) -> bool:
    digits = _normalize_cui(value)
    if not digits.isdigit() or not (2 <= len(digits) <= 10):
        return False
    key = [7, 5, 3, 2, 1, 7, 5, 3, 2]
    body = [int(c) for c in digits[:-1]]
    check = int(digits[-1])
    body = [0] * (9 - len(body)) + body
    total = sum(d * k for d, k in zip(body, key))
    control = (total * 10) % 11
    if control == 10:
        control = 0
    return control == check


def _map_user_fields(fields: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Map user-specified keys to SAGA Clienti columns. Unknown keys are reported, not invented."""
    row: dict[str, str] = {}
    unknown: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value == "":
            continue
        norm = _normalize(str(key)).replace(" ", "_")
        targets = FIELD_ALIASES.get(norm)
        if not targets:
            # Allow exact passthrough for already-canonical SAGA names with odd casing.
            if str(key) in CLIENTI_FIELD_CATALOG:
                targets = (str(key),)
            else:
                unknown.append(str(key))
                continue
        for target in targets:
            row[target] = text_value

    # Normalize only values the user actually provided.
    if "Tara" in row and _normalize(row["Tara"]) in {"romania", "românia", "ro"}:
        row["Tara"] = "RO"
    if "Judet" in row:
        jud = row["Judet"].strip()
        mapped = JUDET_CODES.get(_normalize(jud))
        if mapped:
            row["Judet"] = mapped
        elif len(jud) <= 2:
            row["Judet"] = jud.upper()
    if "Localitate" in row and _normalize(row["Localitate"]) in {"bucuresti", "bucurești"}:
        row["Localitate"] = "BUCURESTI"

    return row, unknown


def _row_data_from_fields(fields: dict[str, Any]) -> dict[str, str]:
    row, _unknown = _map_user_fields(fields)
    return row


COMBO_FIELDS = {"Tara", "Judet", "Localitate", "Nationalitate"}


def _select_clienti_combo(page, field: str, value: str) -> bool:
    """Select a SAGA advanced combo value (Tara/Judet/Localitate)."""
    if not value:
        return False
    # Preferred: drive the live table APIs when available.
    try:
        ok = page.evaluate(
            """([field, value]) => {
                const table = (typeof getTable === 'function') ? getTable('Clienti') : null;
                if (!table || !table.GetSelectedRow) return false;
                const row = table.GetSelectedRow();
                if (!row || !row.length) return false;
                const input = row.find('.rowFieldInput_' + field);
                if (!input.length) return false;
                input.val(value);
                input.attr('data-option', value);
                input.data('option', value);
                if (typeof table.SyncToSelectedData === 'function') {
                    table.SyncToSelectedData(field, value);
                }
                return true;
            }""",
            [field, value],
        )
        if ok:
            page.wait_for_timeout(300)
            return True
    except Exception:
        pass

    toggle = page.locator(
        f"#dropdownToggle_{field}_Clienti, #dropdownToggle_{field}, "
        f".rowFieldInput_{field}"
    )
    if toggle.count() == 0:
        return False
    try:
        toggle.last.click(timeout=3_000)
        page.wait_for_timeout(400)
    except Exception:
        return False

    menu = page.locator(f"#dropdownMenu_{field}_Clienti, #dropdown_{field}_Clienti, .dropdown-menu.show")
    option = page.locator(
        f"#dropdownMenu_{field}_Clienti .dropdown-item, "
        f"#dropdown_{field}_Clienti .dropdown-item, "
        f".dropdown-menu.show .dropdown-item"
    ).filter(has_text=re.compile(re.escape(value), re.I))
    if option.count() == 0:
        # Try typing filter into open combo search input.
        search = page.locator(
            f"#dropdown_{field}_Clienti input, #dropdownMenu_{field}_Clienti input, "
            f".dropdown-menu.show input"
        )
        if search.count() > 0:
            try:
                search.first.fill(value)
                page.wait_for_timeout(400)
            except Exception:
                pass
        option = page.locator(".dropdown-menu.show .dropdown-item, .dropdown-item").filter(
            has_text=re.compile(re.escape(value), re.I)
        )
    if option.count() == 0:
        return False
    try:
        option.first.click(timeout=3_000)
        page.wait_for_timeout(400)
        return True
    except Exception:
        return False


def _fill_clienti_inputs(page, row_data: dict[str, str]) -> list[str]:
    filled: list[str] = []
    # Combos first in dependency order.
    for field in ("Tara", "Judet", "Localitate"):
        if field not in row_data:
            continue
        if _select_clienti_combo(page, field, row_data[field]):
            filled.append(field)

    for field, value in row_data.items():
        if field in COMBO_FIELDS:
            continue
        selectors = [
            f".rowFieldInput_{field}",
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
    return filled


def _merge_clienti_row(current: dict[str, Any], updates: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key, value in (current or {}).items():
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        merged[str(key)] = text
    merged.update(updates)
    return merged


def _post_clienti_row(
    page,
    *,
    path: str,
    row_data: dict[str, str],
    user_validation_flags: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", path.lstrip("/"))
    form: dict[str, str] = {f"Data[{key}]": str(value) for key, value in row_data.items()}
    form["_CHECKED"] = "false"
    form["IsPaste"] = "false"
    if user_validation_flags:
        form["uvf"] = json.dumps(user_validation_flags, ensure_ascii=False)
    response = page.request.post(
        absolute,
        form=form,
        headers=saga_session._auth_headers(page),
        timeout=45_000,
    )
    content_type = response.headers.get("content-type", "")
    try:
        parsed: Any = response.json() if "json" in content_type else response.text()
    except Exception:
        parsed = response.text()
    return {"endpoint": absolute, "status": response.status, "response": parsed, "ok_http": response.ok}


def _click_clienti_toolbar(page, *labels: str) -> bool:
    class_map = {
        "adaug": ".buttonOperationAdd_Clienti",
        "salvez": ".buttonOperationSave_Clienti",
        "salveaza": ".buttonOperationSave_Clienti",
        "salvează": ".buttonOperationSave_Clienti",
        "anulez": ".buttonOperationCancel_Clienti",
        "renunt": ".buttonOperationCancel_Clienti",
        "renunț": ".buttonOperationCancel_Clienti",
        "modific": ".buttonOperationEdit_Clienti",
        "sterg": ".buttonOperationDelete_Clienti",
        "șterg": ".buttonOperationDelete_Clienti",
        "sters": ".buttonOperationDelete_Clienti",
        "șters": ".buttonOperationDelete_Clienti",
        "delete": ".buttonOperationDelete_Clienti",
    }
    for label in labels:
        cls = class_map.get(label.casefold())
        if cls:
            loc = page.locator(cls)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=5_000)
                    page.wait_for_timeout(800)
                    return True
                except Exception:
                    pass
        if saga_session._click_if_visible(page, label):
            return True
    return False


def _dismiss_validation_continue(page) -> bool:
    """Click Da on SAGA CriticalChoice validation modal (e.g. invalid CUI warning)."""
    try:
        body = page.locator("body").inner_text(timeout=2_000)
    except Exception:
        body = ""
    if "doriti sa continuati" not in body.casefold() and "doriți să continuați" not in body.casefold():
        # Still try common modal buttons.
        pass
    for label in ("Da", "Yes"):
        loc = page.get_by_role("button", name=re.compile(rf"^\s*{label}\s*$", re.I))
        if loc.count() == 0:
            loc = page.locator(f'button:has-text("{label}")')
        if loc.count() == 0:
            continue
        try:
            loc.first.click(timeout=3_000)
            page.wait_for_timeout(1_500)
            return True
        except Exception:
            continue
    return saga_session._click_if_visible(page, "Da", "Yes")


def _create_clienti_via_api(
    page,
    row_data: dict[str, str],
    *,
    user_validation_flags: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return _post_clienti_row(
        page,
        path="Clienti/Create_Clienti",
        row_data=row_data,
        user_validation_flags=user_validation_flags,
    )


def _verify_created(page, row_data: dict[str, str]) -> dict[str, Any] | None:
    probed = _probe_data_endpoints(page)
    partners = _rows_from_json((probed or {}).get("body")) if probed else []
    if not partners:
        partners = _scrape_partner_table(page)
    needles = [v for v in (row_data.get("Denumire"), row_data.get("Cod"), row_data.get("CodFiscal")) if v]
    for partner in partners:
        blob = _normalize(json.dumps(partner, ensure_ascii=False))
        if needles and all(_normalize(n) in blob for n in needles[:2]):
            return partner
        den = _normalize(str(partner.get("Denumire") or partner.get("denumire") or ""))
        if row_data.get("Denumire") and den == _normalize(row_data["Denumire"]):
            return partner
    return None


def create_partner(fields: dict[str, Any], *, confirm_write: bool = False) -> dict[str, Any]:
    payload = {str(k): v for k, v in (fields or {}).items() if v is not None and str(v).strip() != ""}
    if not payload:
        return {
            "ok": False,
            "error": "fields cannot be empty.",
            "writable_fields": partner_field_catalog()["fields"],
        }

    row_data, unknown = _map_user_fields(payload)
    if unknown:
        return {
            "ok": False,
            "error": f"Unknown field(s): {', '.join(unknown)}",
            "unknown_fields": unknown,
            "writable_fields": partner_field_catalog()["fields"],
        }
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "create_partner",
            "preview": payload,
            "mapped_fields": row_data,
            "details": (
                "Preview only — only these user-specified fields will be written. "
                "Ask the user to confirm, then call again with confirm_write=true."
            ),
            "writable_fields": [f["name"] for f in partner_field_catalog()["fields"]],
        }

    def _run(browser_page):
        p = _ready(browser_page)
        opened = _open_partners_ui(p)
        if not opened.get("ok"):
            return {"ok": False, **opened}

        saga_session.clear_capture()
        if "Denumire" not in row_data:
            return {"ok": False, "error": "denumire/Denumire is required to create a client.", "request": payload}

        api_result = _create_clienti_via_api(p, row_data)
        parsed = api_result.get("response")
        if isinstance(parsed, dict) and parsed.get("errorCode") == "ValidateData":
            flags = []
            for flag in parsed.get("validationFlags") or []:
                if isinstance(flag, dict) and flag.get("id"):
                    flags.append({"id": flag["id"], "userChoice": "Yes"})
            if flags:
                api_result = _create_clienti_via_api(p, row_data, user_validation_flags=flags)
                parsed = api_result.get("response")

        if isinstance(parsed, dict) and parsed.get("success") is True:
            verified = _verify_created(p, row_data)
            return {
                "ok": True,
                "created": True,
                "via": "api",
                "endpoint": api_result.get("endpoint"),
                "request": payload,
                "row_data": row_data,
                "response": parsed,
                "partner": verified,
                "url": p.url,
                "screenshot_path": _save_partner_capture(p, "saga-partner-created.png"),
                "capture_path": saga_session._dump_capture("network-partner-create.json"),
            }

        # UI path: Adaug → fill only specified fields → Salvez.
        if not _click_clienti_toolbar(p, "Adaug", "Adauga", "Adaugă", "Add"):
            try:
                p.evaluate(
                    "() => { const t = (typeof getTable==='function') ? getTable('Clienti') : null; "
                    "if (t && t.ToolbarActionAdd) return t.ToolbarActionAdd(); return false; }"
                )
                p.wait_for_timeout(800)
            except Exception:
                pass

        filled = _fill_clienti_inputs(p, row_data)
        saved = _click_clienti_toolbar(p, "Salvez", "Salveaza", "Salvează", "Save")
        if saved:
            _dismiss_validation_continue(p)
            p.wait_for_timeout(2_000)

        verified = _verify_created(p, row_data)
        if verified is not None:
            return {
                "ok": True,
                "created": True,
                "via": "ui",
                "request": payload,
                "row_data": row_data,
                "filled_fields": filled,
                "partner": verified,
                "url": p.url,
                "screenshot_path": _save_partner_capture(p, "saga-partner-created.png"),
                "capture_path": saga_session._dump_capture("network-partner-create.json"),
            }

        return {
            "ok": False,
            "error": "Could not create partner via Clienti API or UI form.",
            "request": payload,
            "row_data": row_data,
            "filled_fields": filled,
            "api_response": parsed if isinstance(parsed, dict) else api_result,
            "screenshot_path": _save_partner_capture(p, "saga-partner-create-failed.png"),
            "capture_path": saga_session._dump_capture("network-partner-create.json"),
        }

    return saga_session.run_in_session(_run)


def update_partner(
    partner_id: str,
    fields: dict[str, Any],
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    key = (partner_id or "").strip()
    payload = {str(k): v for k, v in (fields or {}).items() if v is not None and str(v).strip() != ""}
    if not key:
        return {"ok": False, "error": "partner_id cannot be empty."}
    if not payload:
        return {
            "ok": False,
            "error": "fields cannot be empty.",
            "writable_fields": partner_field_catalog()["fields"],
        }

    updates, unknown = _map_user_fields(payload)
    if unknown:
        return {
            "ok": False,
            "error": f"Unknown field(s): {', '.join(unknown)}",
            "unknown_fields": unknown,
            "writable_fields": partner_field_catalog()["fields"],
        }

    existing = get_partner(key)
    if not existing.get("ok"):
        return existing

    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "update_partner",
            "partner_id": key,
            "preview": payload,
            "mapped_fields": updates,
            "current": existing.get("partner"),
            "details": (
                "Preview only — only these user-specified fields will change; "
                "all other current values stay as-is. Confirm then call with confirm_write=true."
            ),
            "writable_fields": [f["name"] for f in partner_field_catalog()["fields"]],
        }

    def _run(browser_page):
        p = _ready(browser_page)
        opened = _open_partners_ui(p)
        if not opened.get("ok"):
            return {"ok": False, **opened}

        saga_session.clear_capture()
        current = existing.get("partner") or {}
        # Merge keeps unspecified current values; only `updates` are user-specified changes.
        row_data = _merge_clienti_row(current, updates)
        if "Cod" not in row_data:
            for pk in ("Cod", "cod", "COD_TERT", "OriginalID", "id"):
                if current.get(pk) is not None:
                    row_data["Cod"] = str(current.get(pk))
                    break

        api_result = _post_clienti_row(p, path="Clienti/Edit_Clienti", row_data=row_data)
        parsed = api_result.get("response")
        if isinstance(parsed, dict) and parsed.get("errorCode") == "ValidateData":
            flags = []
            for flag in parsed.get("validationFlags") or []:
                if isinstance(flag, dict) and flag.get("id"):
                    flags.append({"id": flag["id"], "userChoice": "Yes"})
            if flags:
                api_result = _post_clienti_row(
                    p,
                    path="Clienti/Edit_Clienti",
                    row_data=row_data,
                    user_validation_flags=flags,
                )
                parsed = api_result.get("response")

        if isinstance(parsed, dict) and parsed.get("success") is True:
            verified = _verify_created(p, row_data)
            return {
                "ok": True,
                "updated": True,
                "via": "api",
                "endpoint": api_result.get("endpoint"),
                "partner_id": key,
                "request": payload,
                "changed_fields": updates,
                "row_data": row_data,
                "response": parsed,
                "partner": verified,
                "screenshot_path": _save_partner_capture(p, "saga-partner-updated.png"),
                "capture_path": saga_session._dump_capture("network-partner-update.json"),
            }

        cod = row_data.get("Cod") or key
        try:
            p.evaluate(
                """(cod) => {
                    const table = (typeof getTable === 'function') ? getTable('Clienti') : null;
                    if (!table || !table.GetVirtualData) return false;
                    const data = table.GetVirtualData() || [];
                    for (let i = 0; i < data.length; i++) {
                        const row = data[i] || {};
                        if (String(row.Cod || '') === String(cod) || String(row.Denumire || '') === String(cod)) {
                            if (table.SelectRowByIndex) table.SelectRowByIndex(i);
                            else if (table.SelectRow) table.SelectRow(i);
                            return true;
                        }
                    }
                    return false;
                }""",
                cod,
            )
            p.wait_for_timeout(500)
        except Exception:
            pass

        if not _click_clienti_toolbar(p, "Modific", "Edit"):
            return {
                "ok": False,
                "error": "Could not open edit mode for partner.",
                "partner_id": key,
                "request": payload,
                "api_response": parsed if isinstance(parsed, dict) else api_result,
                "screenshot_path": _save_partner_capture(p, "saga-partner-update-failed.png"),
            }
        filled = _fill_clienti_inputs(p, updates)
        if not _click_clienti_toolbar(p, "Salvez", "Salveaza", "Salvează", "Save"):
            return {
                "ok": False,
                "error": "Could not click save while updating partner.",
                "partner_id": key,
                "filled_fields": filled,
                "screenshot_path": _save_partner_capture(p, "saga-partner-update-failed.png"),
            }
        _dismiss_validation_continue(p)
        p.wait_for_timeout(2_000)
        verified = _verify_created(p, row_data)
        return {
            "ok": verified is not None,
            "updated": verified is not None,
            "via": "ui",
            "partner_id": key,
            "request": payload,
            "changed_fields": updates,
            "row_data": row_data,
            "filled_fields": filled,
            "partner": verified,
            "screenshot_path": _save_partner_capture(
                p, "saga-partner-updated.png" if verified else "saga-partner-update-failed.png"
            ),
            "capture_path": saga_session._dump_capture("network-partner-update.json"),
        }

    return saga_session.run_in_session(_run)


def _clienti_pk(partner: dict[str, Any]) -> str | None:
    for key in ("Cod", "cod", "COD", "OriginalID", "Id", "id", "ID"):
        value = partner.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return _partner_id(partner)


def _partner_still_exists(page, pk: str) -> bool:
    probed = _probe_data_endpoints(page)
    partners = _rows_from_json((probed or {}).get("body")) if probed else []
    if not partners:
        partners = _scrape_partner_table(page)
    needle = _normalize(pk)
    for partner in partners:
        for candidate in (
            partner.get("Cod"),
            partner.get("cod"),
            partner.get("Denumire"),
            partner.get("denumire"),
            _partner_id(partner),
        ):
            if candidate is not None and _normalize(str(candidate)) == needle:
                return True
    return False


def _delete_clienti_via_api(page, pk: str) -> dict[str, Any]:
    """Delete via Clienti/Delete_Clienti using both Ex and classic payloads."""
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", "Clienti/Delete_Clienti")
    headers = saga_session._auth_headers(page)
    attempts: list[dict[str, Any]] = []

    def _post(form: dict[str, Any]) -> dict[str, Any]:
        response = page.request.post(absolute, form=form, headers=headers, timeout=45_000)
        content_type = response.headers.get("content-type", "")
        try:
            parsed: Any = response.json() if "json" in content_type else response.text()
        except Exception:
            parsed = response.text()
        entry = {
            "endpoint": absolute,
            "status": response.status,
            "request": form,
            "response": parsed,
            "ok_http": response.ok,
        }
        attempts.append(entry)
        return entry

    # Ex-style (same family as Create_Clienti success/ValidateData responses).
    result = _post({"ID": pk, "UserValidationFlags": "[]"})
    parsed = result.get("response")
    if isinstance(parsed, dict) and parsed.get("success") is True:
        return {"ok": True, "via": "api_ex", **result, "attempts": attempts}

    if isinstance(parsed, dict) and parsed.get("errorCode") == "ValidateData":
        flags = []
        for flag in parsed.get("validationFlags") or []:
            if isinstance(flag, dict) and flag.get("id"):
                flags.append({"ID": flag["id"], "UserChoice": "Yes"})
            elif isinstance(flag, dict) and flag.get("ID"):
                flags.append({"ID": flag["ID"], "UserChoice": "Yes"})
        if flags:
            result = _post({"ID": pk, "UserValidationFlags": json.dumps(flags, ensure_ascii=False)})
            parsed = result.get("response")
            if isinstance(parsed, dict) and parsed.get("success") is True:
                return {"ok": True, "via": "api_ex", **result, "attempts": attempts}

    # Classic AdvancedControls delete: Id + _CHECKED handshake.
    sender = "0"
    try:
        sender = str(
            page.evaluate(
                "() => (typeof tabID !== 'undefined' && tabID != null) ? String(tabID) : '0'"
            )
            or "0"
        )
    except Exception:
        pass
    result = _post({"Id": pk, "_CHECKED": "false", "SenderID": sender})
    parsed = result.get("response")
    if isinstance(parsed, dict) and parsed.get("type") == "Validation":
        result = _post({"Id": pk, "_CHECKED": "true", "SenderID": sender})
        parsed = result.get("response")
        if result.get("ok_http") and not (
            isinstance(parsed, dict) and parsed.get("type") in ("Warning", "Choice")
        ):
            if not (isinstance(parsed, dict) and parsed.get("success") is False):
                return {"ok": True, "via": "api_classic", **result, "attempts": attempts}

    if isinstance(parsed, dict) and parsed.get("success") is True:
        return {"ok": True, "via": "api_classic", **result, "attempts": attempts}

    return {
        "ok": False,
        "via": "api",
        "endpoint": absolute,
        "attempts": attempts,
        "response": parsed if isinstance(parsed, dict) else result,
    }


def _delete_clienti_via_ui(page, pk: str) -> dict[str, Any]:
    selected = False
    try:
        selected = bool(
            page.evaluate(
                """(cod) => {
                    const table = (typeof getTable === 'function') ? getTable('Clienti') : null;
                    if (!table || !table.GetVirtualData) return false;
                    const data = table.GetVirtualData() || [];
                    for (let i = 0; i < data.length; i++) {
                        const row = data[i] || {};
                        if (String(row.Cod || '') === String(cod)) {
                            if (table.SelectRowByIndex) table.SelectRowByIndex(i);
                            else if (table.SelectRow) table.SelectRow(i);
                            return true;
                        }
                    }
                    return false;
                }""",
                pk,
            )
        )
        page.wait_for_timeout(400)
    except Exception:
        selected = False

    if not selected:
        return {"ok": False, "error": f"Could not select Clienti row Cod={pk} for UI delete."}

    opened_delete = False
    try:
        opened_delete = bool(
            page.evaluate(
                """() => {
                    const table = (typeof getTable === 'function') ? getTable('Clienti') : null;
                    if (table && table.ToolbarActionDelete) {
                        table.ToolbarActionDelete();
                        return true;
                    }
                    const btn = document.querySelector('.buttonOperationDelete_Clienti');
                    if (btn) { btn.click(); return true; }
                    return false;
                }"""
            )
        )
        page.wait_for_timeout(600)
    except Exception:
        opened_delete = False

    if not opened_delete and not _click_clienti_toolbar(
        page, "Sters", "Șters", "Sterg", "Șterg", "Delete"
    ):
        return {"ok": False, "error": "Could not open Clienti delete confirmation."}

    confirmed = False
    for selector in (
        "#buttonOperationDelete_Confirm",
        "#modalDelete #buttonOperationDelete_Confirm",
        'button:has-text("Da")',
        'button:has-text("Confirm")',
    ):
        loc = page.locator(selector)
        if loc.count() == 0:
            continue
        try:
            loc.first.click(timeout=3_000)
            page.wait_for_timeout(1_500)
            confirmed = True
            break
        except Exception:
            continue

    if not confirmed:
        confirmed = _dismiss_validation_continue(page)

    if not confirmed:
        try:
            page.evaluate(
                """() => {
                    const table = (typeof getTable === 'function') ? getTable('Clienti') : null;
                    if (table && table.ToolbarActionDeleteForced) {
                        return table.ToolbarActionDeleteForced();
                    }
                    return false;
                }"""
            )
            page.wait_for_timeout(1_500)
            confirmed = True
        except Exception:
            pass

    return {"ok": confirmed, "via": "ui", "selected": selected, "confirmed": confirmed}


def delete_partner(partner_id: str, *, confirm_write: bool = False) -> dict[str, Any]:
    key = (partner_id or "").strip()
    if not key:
        return {"ok": False, "error": "partner_id cannot be empty."}

    existing = get_partner(key)
    if not existing.get("ok"):
        return existing

    partner = existing.get("partner") or {}
    pk = _clienti_pk(partner)
    if not pk:
        return {
            "ok": False,
            "error": "Could not determine Clienti primary key (Cod) for delete.",
            "partner": partner,
        }

    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "remove_partner",
            "partner_id": key,
            "delete_key": pk,
            "partner": partner,
            "details": (
                "Preview only — this will permanently remove the Clienti row. "
                "Ask the user to confirm, then call again with confirm_write=true."
            ),
        }

    def _run(browser_page):
        p = _ready(browser_page)
        opened = _open_partners_ui(p)
        if not opened.get("ok"):
            return {"ok": False, **opened}

        saga_session.clear_capture()
        api_result = _delete_clienti_via_api(p, pk)
        gone = not _partner_still_exists(p, pk)

        if api_result.get("ok") and gone:
            return {
                "ok": True,
                "deleted": True,
                "via": api_result.get("via"),
                "partner_id": key,
                "delete_key": pk,
                "partner": partner,
                "response": api_result.get("response"),
                "endpoint": api_result.get("endpoint"),
                "screenshot_path": _save_partner_capture(p, "saga-partner-deleted.png"),
                "capture_path": saga_session._dump_capture("network-partner-delete.json"),
            }

        ui_result = _delete_clienti_via_ui(p, pk)
        p.wait_for_timeout(1_500)
        gone = not _partner_still_exists(p, pk)
        if gone:
            return {
                "ok": True,
                "deleted": True,
                "via": ui_result.get("via") or "ui",
                "partner_id": key,
                "delete_key": pk,
                "partner": partner,
                "api_attempts": api_result.get("attempts"),
                "screenshot_path": _save_partner_capture(p, "saga-partner-deleted.png"),
                "capture_path": saga_session._dump_capture("network-partner-delete.json"),
            }

        return {
            "ok": False,
            "deleted": False,
            "error": "Could not delete partner via Clienti API or UI.",
            "partner_id": key,
            "delete_key": pk,
            "partner": partner,
            "api_result": api_result,
            "ui_result": ui_result,
            "screenshot_path": _save_partner_capture(p, "saga-partner-delete-failed.png"),
            "capture_path": saga_session._dump_capture("network-partner-delete.json"),
        }

    return saga_session.run_in_session(_run)

