from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
from xml.etree import ElementTree as ET

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.saga import partners as saga_partners
from markus_mcp.tools.saga import session as saga_session


ROUTE = "ImportDate"
UPLOAD_PATH = "ImportDate/UploadXMLFiles"
IMPORT_PATH = "ImportDate/ImportFactura"
REPORT_PATH = "ImportDate/GetResultImportTXT"
GET_DATA_PATHS = (
    "ImportDate/GetData_ImportDate",
    "ImportDate/GetData",
)
STARE_IMPORT = {
    1: "Neimportat",
    2: "Eroare import",
    3: "Importat partial",
    4: "Importat cu avertizari",
    5: "Importat",
}
MAX_XML_BYTES = 25 * 1024 * 1024
FILENAME_RE = re.compile(r"^F_.+\.xml$", re.IGNORECASE)


def import_xml(xml_path: str, *, confirm_write: bool = False) -> dict[str, Any]:
    preview = preview_xml(xml_path)
    if not preview.get("ok"):
        return preview
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "import_xml",
            "preview": preview,
            "details": (
                "Preview only — this will upload the XML to SAGA Import date "
                f"({preview.get('import_url')}) and run ImportFactura. "
                "Ask the user to confirm, then call again with confirm_write=true."
            ),
        }

    def _run(browser_page):
        page = saga_partners._ready(browser_page)
        opened = _open_import_date(page)
        if not opened.get("ok"):
            return {"ok": False, **opened, "preview": preview}

        source = Path(preview["resolved_path"])
        existing = _find_file(_list_import_files(page), source.name)
        uploaded = None
        if existing and _stare_label(existing.get("stareImport")).casefold() == "importat":
            return {
                "ok": False,
                "error": (
                    f"{source.name} is already marked Importat on Import date. "
                    "Cancel that import in SAGA first if you need to load it again."
                ),
                "file": existing,
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, "saga-import-date.png"),
                "preview": preview,
            }

        if existing is None:
            saga_session.clear_capture()
            uploaded = _upload_xml(page, source)
            if not uploaded.get("ok"):
                return {
                    "ok": False,
                    **uploaded,
                    "url": page.url,
                    "screenshot_path": saga_session._save_screenshot(page, "saga-import-date-upload-failed.png"),
                    "capture_path": saga_session._dump_capture("network-import-date-upload.json"),
                    "preview": preview,
                }
            _reload_import_page(page)
            existing = _find_file(_list_import_files(page), source.name)

        if not existing:
            return {
                "ok": False,
                "error": (
                    f"Uploaded {source.name} but it did not appear on the Import date grid."
                ),
                "upload": uploaded,
                "files": _list_import_files(page),
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, "saga-import-date-missing-row.png"),
                "capture_path": saga_session._dump_capture("network-import-date-upload.json"),
                "preview": preview,
            }

        imported = _import_factura(
            page,
            file_name=str(existing.get("fileName") or source.name),
            destinatie=str(existing.get("destinatie") or ""),
        )
        response = imported.get("response") if isinstance(imported.get("response"), dict) else {}
        stare = _stare_label(response.get("stareImport") if isinstance(response, dict) else None)
        report_path = None
        if stare.casefold() not in {"importat", "neimportat", ""}:
            report_path = _download_import_report(
                page,
                file_name=str(existing.get("fileName") or source.name),
                destinatie=str(existing.get("destinatie") or ""),
            )
        _reload_import_page(page)
        after = _find_file(_list_import_files(page), source.name) or existing
        if not stare:
            stare = _stare_label(after.get("stareImport"))
        stare_l = stare.casefold()
        imported_ok = stare_l in {"importat", "importat cu avertizari"}
        message = ""
        if isinstance(response, dict):
            message = str(response.get("message") or "").strip()
        if not message:
            message = stare or "Import finished."
        return {
            "ok": imported_ok,
            "imported": imported_ok or stare_l == "importat partial",
            "stare_import": stare,
            "destinatie": after.get("destinatie") or existing.get("destinatie"),
            "file_name": after.get("fileName") or source.name,
            "message": message,
            "response": response,
            "upload": uploaded,
            "file": after,
            "report_path": report_path,
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-import-date.png"),
            "capture_path": saga_session._dump_capture("network-import-date.json"),
            "preview": {
                "path": preview.get("path"),
                "filename": preview.get("filename"),
                "invoice_count": preview.get("invoice_count"),
                "total_amount": preview.get("total_amount"),
            },
            "error": None if imported_ok else (message or f"Import ended with status {stare or 'unknown'}."),
        }

    return saga_session.run_in_session(_run)


def preview_xml(xml_path: str) -> dict[str, Any]:
    source = Path(str(xml_path or "")).expanduser()
    if not str(xml_path or "").strip():
        return {"ok": False, "error": "xml_path is required."}
    if not source.is_file():
        return {"ok": False, "error": f"XML file not found: {source}"}
    if source.suffix.casefold() != ".xml":
        return {"ok": False, "error": f"Expected a .xml file, got {source.name}"}
    size = source.stat().st_size
    if size <= 0:
        return {"ok": False, "error": f"{source.name} is empty."}
    if size > MAX_XML_BYTES:
        return {"ok": False, "error": f"{source.name} is larger than 25 MB."}

    try:
        tree = ET.parse(source)
        root_name = _local(tree.getroot().tag)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"Invalid XML: {exc}", "path": str(source)}
    if root_name.casefold() in {"incasari", "plati"}:
        return {
            "ok": False,
            "error": (
                f"{source.name} is a SAGA {root_name} XML (I_/P_), not Facturi (F_). "
                "Use saga_import_incasari_xml on Jurnal de Bancă / Import extrase, "
                "not saga_import_xml."
            ),
            "tool": "saga_import_incasari_xml",
            "path": _host(source),
            "filename": source.name,
        }

    try:
        summary = summarize_facturi_xml(source)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"Invalid XML: {exc}", "path": str(source)}

    warnings: list[str] = []
    if not FILENAME_RE.match(source.name):
        warnings.append(
            "SAGA Import date expects F_<cif>_<dd>_<mm>_<yyyy>.xml; "
            f"this file is named {source.name}."
        )
    if summary.get("invoice_count", 0) == 0:
        warnings.append("No <Factura> nodes found; SAGA may reject this file.")
    if any(item.get("customer_cod") for item in summary.get("invoices") or []):
        warnings.append(
            "This file has <ClientCod> (sales Ieșiri export). "
            "Use saga_import_iesiri_xml to create RON Ieșiri and keep NrDoc. "
            "Import date typically loads purchases onto Intrări valută."
        )

    return {
        "ok": True,
        "path": _host(source),
        "resolved_path": str(source),
        "filename": source.name,
        "size_bytes": size,
        "import_url": f"{saga_session.DEFAULT_APP_BASE_URL}/{ROUTE}",
        "invoice_count": summary.get("invoice_count", 0),
        "line_count": summary.get("line_count", 0),
        "total_amount": summary.get("total_amount"),
        "invoices": summary.get("invoices") or [],
        "warnings": warnings,
        "details": (
            f"Will upload {source.name} to Import date and import "
            f"{summary.get('invoice_count', 0)} invoice(s)."
        ),
    }


def summarize_facturi_xml(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    facturi = _findall(root, "Factura")
    invoices: list[dict[str, Any]] = []
    line_count = 0
    total_amount = 0.0
    for factura in facturi:
        antet = _find(factura, "Antet") or factura
        lines = _findall(factura, "Linie")
        line_count += len(lines)
        amount = 0.0
        for line in lines:
            amount += _number(_child_text(line, "Valoare")) + _number(_child_text(line, "TVA"))
        total_amount += amount
        invoices.append(
            {
                "number": _child_text(antet, "FacturaNumar"),
                "date": _child_text(antet, "FacturaData"),
                "supplier": _child_text(antet, "FurnizorNume"),
                "supplier_cif": _child_text(antet, "FurnizorCIF"),
                "customer": _child_text(antet, "ClientNume"),
                "customer_cif": _child_text(antet, "ClientCIF"),
                "customer_cod": _child_text(antet, "ClientCod"),
                "currency": _child_text(antet, "FacturaMoneda") or "RON",
                "line_count": len(lines),
                "amount": round(amount, 2),
            }
        )
    return {
        "invoice_count": len(facturi),
        "line_count": line_count,
        "total_amount": round(total_amount, 2),
        "invoices": invoices[:30],
    }


def _open_import_date(page) -> dict[str, Any]:
    saga_session.clear_capture()
    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", ROUTE)
    current = (page.url or "").casefold()
    if "/sagac/importdate" in current:
        return {"ok": True, "url": page.url, "via": "current"}
    if not saga_partners._safe_goto(page, url):
        return {
            "ok": False,
            "error": f"Could not open Import date at {url}",
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-import-date-missing.png"),
        }
    page.wait_for_timeout(2_000)
    body = ""
    try:
        body = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        pass
    markers = ("import", "xml", "fișier", "fisier", "adaug")
    if any(token in body.casefold() for token in markers) or "/importdate" in (page.url or "").casefold():
        return {"ok": True, "url": page.url, "via": "route"}
    return {
        "ok": False,
        "error": "Opened a page but Import date markers were not found.",
        "url": page.url,
        "screenshot_path": saga_session._save_screenshot(page, "saga-import-date-missing.png"),
    }


def _reload_import_page(page) -> None:
    try:
        page.reload(wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        _open_import_date(page)
    page.wait_for_timeout(1_500)


def _upload_xml(page, xml_path: Path) -> dict[str, Any]:
    api = _upload_via_api(page, xml_path)
    parsed = api.get("response")
    if api.get("ok_http") and isinstance(parsed, dict) and parsed.get("success") is True:
        return {"ok": True, "via": "api", **api}
    if api.get("ok_http") and isinstance(parsed, dict) and parsed.get("success") is False:
        return {
            "ok": False,
            "error": str(parsed.get("message") or "SAGA rejected the XML upload."),
            "via": "api",
            **api,
        }
    ui = _upload_via_input(page, xml_path)
    if ui.get("ok"):
        return ui
    return {
        "ok": False,
        "error": ui.get("error") or api.get("error") or "XML upload failed.",
        "api": api,
        "ui": ui,
    }


def _upload_via_api(page, xml_path: Path) -> dict[str, Any]:
    absolute = _abs(page, UPLOAD_PATH)
    try:
        response = page.request.post(
            absolute,
            multipart={
                "files": {
                    "name": xml_path.name,
                    "mimeType": "text/xml",
                    "buffer": xml_path.read_bytes(),
                }
            },
            headers=saga_session._auth_headers(page),
            timeout=120_000,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok_http": False, "error": f"UploadXMLFiles failed: {exc}", "endpoint": absolute}
    return {
        "endpoint": absolute,
        "status": response.status,
        "ok_http": response.ok,
        "response": _parse_body(response),
    }


def _upload_via_input(page, xml_path: Path) -> dict[str, Any]:
    locator = page.locator("#fileInputXML")
    try:
        locator.wait_for(state="attached", timeout=15_000)
    except Exception:
        try:
            page.locator("#buttonAdaugaFisiereXML").click(timeout=5_000)
        except Exception:
            return {"ok": False, "error": "Import date file input #fileInputXML was not found."}
        locator.wait_for(state="attached", timeout=10_000)
    try:
        with page.expect_response(lambda r: "UploadXMLFiles" in (r.url or ""), timeout=120_000) as pending:
            locator.set_input_files(str(xml_path))
        response = pending.value
        parsed = _parse_body(response)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"UI XML upload failed: {exc}", "via": "input"}
    if isinstance(parsed, dict) and parsed.get("success") is False:
        return {
            "ok": False,
            "error": str(parsed.get("message") or "SAGA rejected the XML upload."),
            "via": "input",
            "response": parsed,
        }
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except Exception:
        pass
    return {"ok": True, "via": "input", "response": parsed}


def _import_factura(page, *, file_name: str, destinatie: str) -> dict[str, Any]:
    params = {"fileName": file_name, "destinatie": destinatie}
    get_result = _request(page, "GET", IMPORT_PATH, params=params, timeout=180_000)
    parsed = get_result.get("response")
    if get_result.get("ok_http") and isinstance(parsed, dict) and "stareImport" in parsed:
        return get_result
    post_result = _request(page, "POST", IMPORT_PATH, form=params, timeout=180_000)
    if post_result.get("ok_http"):
        return post_result
    return get_result if get_result.get("ok_http") else post_result


def _download_import_report(page, *, file_name: str, destinatie: str) -> str | None:
    result = _request(
        page,
        "GET",
        REPORT_PATH,
        params={"filename": file_name, "destinatie": destinatie},
        timeout=60_000,
    )
    body = result.get("raw")
    if not result.get("ok_http") or not body:
        return None
    saga_session.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]+", "_", file_name.rsplit(".", 1)[0])
    path = saga_session.ARTIFACT_DIR / f"{safe}_RaportImport.txt"
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(str(body), encoding="utf-8")
    return saga_session._host_path(path)


def _list_import_files(page) -> list[dict[str, Any]]:
    rows = _list_files_from_api(page)
    if rows:
        return rows
    return _list_files_from_dom(page)


def _list_files_from_api(page) -> list[dict[str, Any]]:
    params = {"RequestSetup": saga_partners._request_setup(skip=0, batch_size=200)}
    for path in GET_DATA_PATHS:
        result = _request(page, "GET", path, params=params, timeout=30_000)
        if not result.get("ok_http"):
            continue
        rows = saga_partners._rows_from_json(result.get("response"))
        out: list[dict[str, Any]] = []
        for row in rows:
            name = _first(row, "FisierSursa", "fileName", "FileName", "Fisier")
            if not name:
                continue
            out.append(
                {
                    "fileName": name,
                    "destinatie": _first(row, "Destinatie", "destinatie"),
                    "stareImport": row.get("StareImport", row.get("stareImport")),
                }
            )
        if out:
            return out
    return []


def _list_files_from_dom(page) -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """() => {
                const cells = Array.from(document.querySelectorAll('.rowCell_FisierSursa'));
                return cells.map(cell => {
                    const row = cell.closest('.tableRow')
                        || cell.closest('[class*="tableRow"]')
                        || cell.parentElement?.parentElement
                        || cell.parentElement;
                    const dest = row?.querySelector('.rowCell_Destinatie span, .rowCell_Destinatie');
                    const stare = row?.querySelector(
                        '.rowFieldText_StareImport, .rowCell_StareImport span, .rowCell_StareImport'
                    );
                    const nameEl = cell.querySelector('span') || cell;
                    return {
                        fileName: (nameEl.textContent || '').trim(),
                        destinatie: (dest?.textContent || '').trim(),
                        stareImport: (stare?.textContent || '').trim(),
                    };
                }).filter(r => r.fileName);
            }"""
        )
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _find_file(files: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    needle = name.casefold()
    for row in files:
        if str(row.get("fileName") or "").casefold() == needle:
            return row
    for row in files:
        if needle in str(row.get("fileName") or "").casefold():
            return row
    return None


def _request(
    page,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    timeout: int = 60_000,
) -> dict[str, Any]:
    absolute = _abs(page, path)
    headers = saga_session._auth_headers(page)
    try:
        if method.upper() == "GET":
            url = f"{absolute}?{urlencode(params or {})}" if params else absolute
            response = page.request.get(url, headers=headers, timeout=timeout)
        else:
            response = page.request.post(
                absolute,
                form=form,
                params=params,
                headers=headers,
                timeout=timeout,
            )
    except Exception as exc:  # noqa: BLE001
        return {"ok_http": False, "error": str(exc), "endpoint": absolute, "method": method}
    raw: Any
    try:
        raw = response.body()
    except Exception:
        raw = None
    return {
        "endpoint": absolute,
        "method": method,
        "status": response.status,
        "ok_http": response.ok,
        "response": _parse_body(response),
        "raw": raw,
    }


def _parse_body(response) -> Any:
    content_type = (response.headers or {}).get("content-type", "")
    try:
        if "json" in content_type:
            return response.json()
    except Exception:
        pass
    try:
        text = response.text()
    except Exception:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _abs(page, path: str) -> str:
    return urljoin(saga_session.app_base_url(page).rstrip("/") + "/", path.lstrip("/"))


def _stare_label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        return STARE_IMPORT.get(int(value), str(value))
    return str(value).strip()


def _first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _findall(node: ET.Element, tag: str) -> list[ET.Element]:
    tag_l = tag.casefold()
    found = [child for child in node.iter() if _local(child.tag).casefold() == tag_l]
    return found


def _find(node: ET.Element, tag: str) -> ET.Element | None:
    matches = _findall(node, tag)
    return matches[0] if matches else None


def _child_text(node: ET.Element, tag: str) -> str:
    child = None
    tag_l = tag.casefold()
    for item in list(node):
        if _local(item.tag).casefold() == tag_l:
            child = item
            break
    if child is None:
        child = _find(node, tag)
    if child is None or child.text is None:
        return ""
    return str(child.text).strip()


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _number(value: str) -> float:
    try:
        return float((value or "0").replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


def _host(path: Path) -> str:
    data = data_dir()
    try:
        return str(host_data_dir() / path.relative_to(data))
    except ValueError:
        return str(path)
