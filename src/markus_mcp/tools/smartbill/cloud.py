from __future__ import annotations

import json
import os
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.smartbill.credentials import load_credentials

DATA_DIR = data_dir()
HOST_DATA_DIR = host_data_dir()
SESSION_DIR = Path(os.getenv("SMARTBILL_SESSION_DIR", "") or (DATA_DIR / "smartbill-session"))
ARTIFACT_DIR = DATA_DIR / "smartbill"
AJAX_HINT = "documente_furnizori/ajax"
HEADLESS = os.getenv("SMARTBILL_HEADLESS", "true").lower() not in {"0", "false", "no"}
CLOUD_URL = "https://cloud.smartbill.ro"
REPORT_PATH = "/achizitii/raport/documente_furnizori/"
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

T = TypeVar("T")

_playwright = None
_context = None
_jobs: queue.Queue[tuple[Callable[[], Any], threading.Event, dict[str, Any]] | None] = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
_captured: list[dict[str, Any]] = []
_capture_lock = threading.Lock()

_JSON_HINTS = (
    "achizit",
    "furniz",
    "expense",
    "cheltu",
    "document",
    "raport",
    "report",
    "export",
    "xls",
    "excel",
    "invoice",
    "spv",
)


def _host_path(path: Path) -> str:
    try:
        relative = path.relative_to(DATA_DIR)
    except ValueError:
        return str(path)
    return str(HOST_DATA_DIR / relative)


def _ensure_dirs() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _clear_locks() -> None:
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = SESSION_DIR / name
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
        except OSError:
            pass


def _launch_context(playwright):
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=HEADLESS,
        user_agent=CHROME_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="ro-RO",
        accept_downloads=True,
        args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )


def _first_page(context):
    return context.pages[0] if context.pages else context.new_page()


def _close_browser() -> None:
    global _playwright, _context
    if _context is not None:
        try:
            _context.close()
        except Exception:
            pass
        _context = None
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _ensure_browser():
    global _playwright, _context
    _ensure_dirs()
    if _context is not None:
        try:
            _ = _context.pages
            return _first_page(_context)
        except Exception:
            _close_browser()
    _clear_locks()
    _playwright = sync_playwright().start()
    _context = _launch_context(_playwright)
    page = _first_page(_context)
    page.on("response", _on_response)
    return page


def _worker_loop() -> None:
    while True:
        item = _jobs.get()
        if item is None:
            _close_browser()
            return
        fn, done, box = item
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            done.set()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="smartbill-browser", daemon=True)
        thread.start()
        _worker_started = True


def _run(fn: Callable[[], T]) -> T:
    _ensure_worker()
    done = threading.Event()
    box: dict[str, Any] = {}
    _jobs.put((fn, done, box))
    done.wait()
    if "error" in box:
        raise box["error"]
    return box["value"]


def _on_response(response) -> None:
    url = response.url or ""
    lowered = url.casefold()
    if not any(hint in lowered for hint in _JSON_HINTS):
        return
    ctype = (response.headers or {}).get("content-type", "")
    rec: dict[str, Any] = {
        "url": url,
        "status": response.status,
        "method": response.request.method,
        "content_type": ctype,
    }
    try:
        rec["post_data"] = (response.request.post_data or "")[:2000]
    except Exception:
        pass
    try:
        if "json" in ctype or "javascript" in ctype:
            rec["json"] = response.json()
        elif "excel" in ctype or "spreadsheet" in ctype or "octet-stream" in ctype:
            rec["bytes_hint"] = True
    except Exception:
        pass
    with _capture_lock:
        _captured.append(rec)


def _dump_capture(name: str = "network-documente-furnizori.json") -> str:
    _ensure_dirs()
    path = ARTIFACT_DIR / name
    with _capture_lock:
        slim = []
        for item in _captured[-80:]:
            copy = {k: v for k, v in item.items() if k != "json"}
            data = item.get("json")
            if data is not None:
                copy["json_preview"] = _preview_json(data)
            slim.append(copy)
    path.write_text(json.dumps(slim, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return _host_path(path)


def _preview_json(data: Any, limit: int = 4000) -> Any:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return data
    return text[:limit] + "…"


def _save_screenshot(page, name: str) -> str:
    _ensure_dirs()
    path = ARTIFACT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    return _host_path(path)


def _logged_in(page) -> bool:
    url = (page.url or "").casefold()
    if any(token in url for token in ("/login", "autentificare", "intra-in-cont")):
        return False
    if "/achizitii" in url or "/documente" in url or "/dashboard" in url or "/raport" in url:
        return True
    try:
        text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return False
    lowered = text.casefold()
    if "intra in cont" in lowered and "parola" in lowered and "e-mail" in lowered:
        return False
    return "documente furnizori" in lowered or "ieșire" in lowered or "iesire cont" in lowered


def _dismiss_modals(page) -> None:
    for label in ("Accept", "Acceptă", "OK", "Continuă", "Continua", "Inchide", "Închide"):
        loc = page.get_by_role("button", name=label)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=1_500)
        except Exception:
            continue


def _login(page) -> dict[str, Any]:
    creds = load_credentials()
    if not creds.username_configured:
        return {"ok": False, "error": "SmartBill email is missing (smartbill_username or saga_username)."}
    if not creds.password_configured:
        return {
            "ok": False,
            "error": (
                "SmartBill Cloud password is missing. Set smartbill_password in private.data "
                "(or reuse saga_password)."
            ),
        }

    page.goto(f"{CLOUD_URL}/", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(1_500)
    _dismiss_modals(page)
    if _logged_in(page):
        return {"ok": True, "details": "Reused SmartBill Cloud session.", "url": page.url}

    user = page.locator('input[type="email"], input[name="email"], input[name="username"], input#username')
    pwd = page.locator('input[type="password"]')
    try:
        user.first.wait_for(state="visible", timeout=20_000)
        pwd.first.wait_for(state="visible", timeout=20_000)
        user.first.fill(creds.username)
        pwd.first.fill(creds.password)
        submit = page.locator('button[type="submit"], input[type="submit"]')
        if submit.count():
            submit.first.click()
        else:
            page.get_by_role("button", name=re.compile("cont|login|intr", re.I)).first.click()
        page.wait_for_timeout(4_000)
    except PlaywrightTimeoutError:
        return {
            "ok": False,
            "error": "SmartBill login form did not appear.",
            "url": page.url,
            "screenshot_path": _save_screenshot(page, "smartbill-login-missing.png"),
        }

    _dismiss_modals(page)
    for label in ("Continua", "Continuă", "Actualizeaza datele", "Actualizează datele"):
        loc = page.get_by_role("button", name=re.compile(label, re.I))
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2_000)
                page.wait_for_timeout(2_000)
        except Exception:
            continue

    if not _logged_in(page):
        try:
            body = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            body = ""
        if "incorecte" in body.casefold() or "autentificare" in body.casefold() and "esuat" in body.casefold():
            detail = (
                "SmartBill rejected the email/password. Set smartbill_password in "
                "private.data (it is not the API token, and may differ from saga_password)."
            )
        else:
            detail = "SmartBill Cloud login failed. Check email/password in private.data."
        return {
            "ok": False,
            "error": detail,
            "url": page.url,
            "screenshot_path": _save_screenshot(page, "smartbill-login-failed.png"),
        }
    return {"ok": True, "details": "Logged in to SmartBill Cloud.", "url": page.url}


def _goto_report(page) -> None:
    page.goto(f"{CLOUD_URL}{REPORT_PATH}", wait_until="domcontentloaded", timeout=90_000)
    try:
        page.wait_for_function("() => typeof window.getData === 'function'", timeout=45_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(2_000)
    _dismiss_modals(page)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass


def _iso_to_dmy(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return value


def _parse_doc_date(value: str) -> str:
    """Normalize SmartBill dates (DD/MM/YYYY, DD.MM.YYYY, YYYY-MM-DD) to ISO."""
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    match = re.match(r"^(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if match:
        day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) == 8:
        if int(digits[:4]) > 1900:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        return f"{digits[4:8]}-{digits[2:4]}-{digits[:2]}"
    return ""


def _set_period_filter(page, date_from: str, date_to: str) -> None:
    period = f"{_iso_to_dmy(date_from)} - {_iso_to_dmy(date_to)}"
    page.evaluate(
        """(period) => {
            const input = document.querySelector('input.period_filter');
            if (!input) return;
            input.value = period;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        period,
    )


def _select_section(page, saved_only: int) -> None:
    group = "saved" if saved_only else "unsaved"
    loc = page.locator(f'.network-status-group button[data-group-status="{group}"]')
    clicked = False
    try:
        if loc.count() and loc.first.is_visible():
            loc.first.click(timeout=3_000)
            clicked = True
    except Exception:
        clicked = False
    if not clicked:
        label = r"^salvate$" if saved_only else r"^nesalvate$"
        tab = page.get_by_text(re.compile(label, re.I))
        try:
            if tab.count() and tab.first.is_visible():
                tab.first.click(timeout=3_000)
        except Exception:
            pass
    page.wait_for_timeout(2_000)


def _fetch_report_page(page, payload: dict[str, Any]) -> dict[str, Any]:
    data = page.evaluate(
        """async (payload) => {
            const sSearch = JSON.stringify(payload);
            window.oldSearch = sSearch;
            const reportUrl = window.REPORT_URL || '/achizitii/raport/documente_furnizori/ajax/';
            if (window.jQuery && window.jQuery.ajax) {
                return await new Promise((resolve) => {
                    window.jQuery.ajax({
                        dataType: 'json',
                        type: 'POST',
                        url: reportUrl,
                        cache: false,
                        data: { sSearch, networkEnabled: window.networkEnabled },
                        success: (json) => resolve(json || {}),
                        error: (xhr) => resolve({
                            errorText: ((xhr && xhr.responseText) || '').slice(0, 500),
                            statusCode: xhr && xhr.status,
                            documents: [],
                        }),
                    });
                });
            }
            const body = new URLSearchParams();
            body.set('sSearch', sSearch);
            body.set('networkEnabled', window.networkEnabled ? 'true' : 'false');
            const res = await fetch(reportUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: body.toString(),
                credentials: 'same-origin',
            });
            const text = await res.text();
            try { return JSON.parse(text); }
            catch (e) { return { errorText: text.slice(0, 500), documents: [] }; }
        }""",
        payload,
    )
    return data if isinstance(data, dict) else {}


def _fetch_documents(page, date_from: str, date_to: str, saved_only: int) -> list[dict[str, Any]]:
    _set_period_filter(page, date_from, date_to)
    dfrom, dto = _iso_to_dmy(date_from), _iso_to_dmy(date_to)
    collected: list[dict[str, Any]] = []
    page_no = 1
    per_page = 100
    while page_no <= 50:
        payload = {
            "from": dfrom,
            "to": dto,
            "page": page_no,
            "results_per_page": per_page,
            "saved_only": saved_only,
            "tip_document": "Factura,Proforma,Bon fiscal,Aviz,Carnet comercializare,Altul",
            "docNumber": "",
            "currency": "",
            "document_status": (
                "Info,In prelucrare,Salvat,Platit,Partial,Depasit"
                if saved_only
                else "In asteptare,Nesalvat,Returnat"
            ),
        }
        if not saved_only:
            payload["document_einvoice_association"] = ""
        data = _fetch_report_page(page, payload)
        if data.get("csrf_fails"):
            raise RuntimeError("SmartBill rejected the report request (CSRF). Try again after a Cloud login.")
        if data.get("errorText") and not data.get("documents"):
            raise RuntimeError(str(data.get("errorText")))
        docs = data.get("documents") or []
        if isinstance(docs, list):
            collected.extend([row for row in docs if isinstance(row, dict)])
        try:
            total = int(data.get("totalCount") or 0)
        except (TypeError, ValueError):
            total = 0
        if not docs:
            break
        if total and len(collected) >= total:
            break
        if len(docs) < per_page:
            break
        page_no += 1
    return collected


def _saved_flags(section: str) -> list[int]:
    value = (section or "all").strip().lower()
    if value in {"saved", "salvate"}:
        return [1]
    if value in {"unsaved", "nesalvate"}:
        return [0]
    return [1, 0]


def _object_lists(data: Any, found: list[list[dict[str, Any]]] | None = None) -> list[list[dict[str, Any]]]:
    found = found if found is not None else []
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        found.append(data)
    elif isinstance(data, dict):
        for value in data.values():
            _object_lists(value, found)
    elif isinstance(data, list):
        for value in data:
            _object_lists(value, found)
    return found


def _score_row(row: dict[str, Any]) -> int:
    blob = " ".join(str(k) for k in row).casefold()
    score = 0
    for token in ("furniz", "supplier", "cif", "total", "tva", "serie", "numar", "number", "data"):
        if token in blob:
            score += 1
    return score


def _rows_from_capture() -> tuple[list[dict[str, Any]], str | None]:
    best: list[dict[str, Any]] = []
    source = None
    ajax_docs: list[dict[str, Any]] = []
    with _capture_lock:
        items = list(_captured)
    for item in items:
        data = item.get("json")
        url = item.get("url") or ""
        if AJAX_HINT in url and isinstance(data, dict):
            docs = data.get("documents")
            if isinstance(docs, list) and docs and all(isinstance(x, dict) for x in docs):
                ajax_docs.extend(docs)
                source = url
    if ajax_docs:
        return ajax_docs, source
    for item in items:
        data = item.get("json")
        if data is None:
            continue
        for candidate in _object_lists(data):
            if not candidate:
                continue
            score = _score_row(candidate[0])
            if score >= 2 and len(candidate) >= len(best):
                best = candidate
                source = item.get("url")
    return best, source


def _row_date(row: dict[str, Any]) -> str:
    lowered = {str(k).casefold(): v for k, v in row.items()}
    for key in ("docdate", "issuedate", "datadocument", "datadoc", "data"):
        if key in lowered and lowered[key] not in (None, ""):
            return str(lowered[key])
    for key, val in row.items():
        name = str(key).casefold()
        if "due" in name:
            continue
        if any(token in name for token in ("data", "date")):
            return str(val or "")
    return ""


def _in_range(value: str, date_from: str, date_to: str) -> bool:
    iso = _parse_doc_date(value)
    if iso:
        return date_from <= iso <= date_to
    return True


def _filter_rows(rows: list[dict[str, Any]], date_from: str, date_to: str) -> list[dict[str, Any]]:
    kept = []
    for row in rows:
        stamp = _row_date(row)
        if not stamp or _in_range(stamp, date_from, date_to):
            kept.append(row)
    return kept


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "type": ("docType", "tip", "type", "documentType"),
        "series": ("serie", "series", "seriesName"),
        "number": ("nrDoc", "numar", "number", "nr", "documentNumber"),
        "supplier": ("supplierName", "furnizor", "supplier", "client", "name", "denumire"),
        "cif": ("supplierCif", "cif", "cui", "vatCode", "codFiscal"),
        "date": ("docDate", "issueDate", "dataDocument", "dataDoc", "data"),
        "due_date": ("dueDate", "scadenta", "dataScadenta"),
        "category": ("categorie", "category"),
        "net": ("totalWithoutVat", "valoareFaraTva", "net", "valueWithoutVat", "value"),
        "vat": ("totalVat", "tva", "vat", "valoareTva"),
        "total": ("totalWithVat", "total", "valoareTotala", "amount"),
        "currency": ("moneda", "currency", "valuta"),
        "nir": ("nirsSerialNo", "nir", "nirIds"),
        "observations": ("observations", "observatii"),
        "saved": ("salvat", "saved", "isSaved"),
        "status": ("status", "stare"),
    }
    lowered = {str(k).casefold(): v for k, v in row.items()}
    out: dict[str, Any] = {}
    for dest, aliases in mapping.items():
        for alias in aliases:
            if alias.casefold() in lowered:
                out[dest] = lowered[alias.casefold()]
                break
    if not out:
        return {str(k): v for k, v in row.items() if not str(k).startswith("_")}
    return out


def _export_cells(inv: dict[str, Any]) -> list[object]:
    return [
        inv.get("number", ""),
        inv.get("nir", ""),
        inv.get("supplier", ""),
        inv.get("cif", ""),
        inv.get("date", ""),
        inv.get("due_date", ""),
        inv.get("category", ""),
        inv.get("net", ""),
        inv.get("vat", ""),
        inv.get("total", ""),
        inv.get("currency", ""),
        inv.get("observations", ""),
        inv.get("status", ""),
    ]


def _table_rows(page) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tables = page.locator("table")
    if tables.count() == 0:
        return rows
    table = tables.first
    headers = [t.strip() for t in table.locator("thead th, thead td").all_inner_texts()]
    body = table.locator("tbody tr")
    count = min(body.count(), 500)
    for i in range(count):
        cells = [t.strip() for t in body.nth(i).locator("td").all_inner_texts()]
        if not cells or all(not c for c in cells):
            continue
        if headers and len(headers) == len(cells):
            rows.append(dict(zip(headers, cells)))
        else:
            rows.append({f"col_{n}": val for n, val in enumerate(cells)})
    return rows


def _click_export(page, dest: Path) -> str | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for opener in (
        page.get_by_text(re.compile(r"descarca e-facturi|e-facturi preluate|descarcă e-facturi", re.I)),
        page.locator("#btn_export"),
        page.locator(".dropdown-toggle, [data-toggle='dropdown']").filter(
            has_text=re.compile(r"excel|export|descarca|descarcă", re.I)
        ),
    ):
        try:
            if opener.count() and opener.first.is_visible():
                opener.first.click(timeout=2_000)
                page.wait_for_timeout(500)
                break
        except Exception:
            continue
    candidates = [
        page.get_by_role("button", name=re.compile(r"excel", re.I)),
        page.get_by_text(re.compile(r"export\s*excel", re.I)),
        page.get_by_text(re.compile(r"exportă excel", re.I)),
        page.get_by_text(re.compile(r"exporta excel", re.I)),
        page.locator('[onclick*="export_excel"]'),
    ]
    for loc in candidates:
        try:
            if loc.count() == 0:
                continue
            with page.expect_download(timeout=30_000) as pending:
                loc.first.click()
            download = pending.value
            suffix = Path(download.suggested_filename or "export.xls").suffix or ".xls"
            path = dest.with_suffix(suffix)
            download.save_as(str(path))
            return _host_path(path)
        except Exception:
            continue
    return None


def _native_xls(page, dest: Path) -> str | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _click_export(page, dest)


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("docId") or row.get("rowId") or row.get("nrDoc") or "")
        if not key:
            key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _list_impl(date_from: str, date_to: str, section: str, limit: int) -> dict[str, Any]:
    with _capture_lock:
        _captured.clear()
    page = _ensure_browser()
    login = _login(page)
    if not login.get("ok"):
        return login
    _goto_report(page)
    _set_period_filter(page, date_from, date_to)

    rows: list[dict[str, Any]] = []
    via = "ajax"
    warnings: list[str] = []
    section_counts = {"saved": 0, "unsaved": 0}
    for saved_only in _saved_flags(section):
        try:
            fetched = _fetch_documents(page, date_from, date_to, saved_only)
            section_counts["saved" if saved_only else "unsaved"] = len(fetched)
            rows.extend(fetched)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"saved_only={saved_only}: {exc}")
        page.wait_for_timeout(500)
    rows = _dedupe_rows(rows)
    captured, source = _rows_from_capture()
    if captured:
        rows = _dedupe_rows(rows + captured)
        if not source:
            source = f"{CLOUD_URL}{REPORT_PATH}ajax/"
    if not rows:
        via = "xhr" if captured else "none"
    if not rows:
        rows = _table_rows(page)
        via = "table" if rows else "none"
        source = page.url
    filtered = _filter_rows(rows, date_from, date_to)
    normalized = [_normalize_row(r) for r in filtered]
    truncated = len(normalized) > limit
    capture_path = _dump_capture()
    result = {
        "ok": True,
        "via": via,
        "date_from": date_from,
        "date_to": date_to,
        "section": section,
        "count": len(normalized),
        "truncated": truncated,
        "invoices": normalized[:limit],
        "source_url": source,
        "url": page.url,
        "capture_path": capture_path,
        "screenshot_path": _save_screenshot(page, "smartbill-documente-furnizori.png"),
        "section_counts": section_counts,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _export_impl(date_from: str, date_to: str, section: str, dest: Path) -> dict[str, Any]:
    listed = _list_impl(date_from, date_to, section, limit=10_000)
    if not listed.get("ok"):
        return listed
    page = _first_page(_context)
    native = None
    if (section or "all").strip().lower() not in {"all", ""}:
        native = _native_xls(page, dest)
        if native:
            return {
                **{k: listed[k] for k in ("date_from", "date_to", "section", "count", "via") if k in listed},
                "ok": True,
                "path": native,
                "row_count": listed.get("count"),
                "export": "smartbill_excel",
            }
    from markus_mcp.tools.smartbill.xlsx import write_xls

    invoices = listed.get("invoices") or []
    headers = [
        "Document furnizor",
        "NIR",
        "Denumire furnizor",
        "CIF",
        "Data doc",
        "Data scadentei",
        "Categoria",
        "Valoare fara TVA",
        "TVA",
        "Valoare totala",
        "Moneda",
        "Observatii",
        "Status",
    ]
    body = [_export_cells(inv) for inv in invoices]
    xls_path = dest.with_suffix(".xls")
    write_xls(xls_path, headers, body)
    return {
        "ok": True,
        "path": _host_path(xls_path),
        "row_count": len(invoices),
        "date_from": date_from,
        "date_to": date_to,
        "section": section,
        "export": "generated_xls",
        "via": listed.get("via"),
        "screenshot_path": listed.get("screenshot_path"),
        "capture_path": listed.get("capture_path"),
        "section_counts": listed.get("section_counts"),
    }


def list_invoices(date_from: str, date_to: str, section: str = "all", limit: int = 200) -> dict[str, Any]:
    return _run(lambda: _list_impl(date_from, date_to, section, limit))


def export_invoices(date_from: str, date_to: str, section: str, dest: Path) -> dict[str, Any]:
    return _run(lambda: _export_impl(date_from, date_to, section, dest))
