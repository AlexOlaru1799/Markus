"""Import SAGA I_/P_ XML (Încasări / Plăți) via Jurnal de Bancă → Import extrase."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from markus_mcp.tools.saga import import_date as saga_import_date
from markus_mcp.tools.saga import partners as saga_partners
from markus_mcp.tools.saga import session as saga_session


JURNAL_ROUTE = "JurnalDeBanca"
IMPORT_ROUTE = "importextrase"
UPLOAD_PATH = "RegistruCasa/IncarcaExtras"
CLEAR_CACHE_PATH = "RegistruCasa/ClearCacheImport"
GET_EXTRASE = "ImportExtrase/GetData_ImportExtrase"
GET_EXTRASE_DET = "ImportExtrase/GetData_ImportExtraseDet"
UPDATE_EXTRASE = "ImportExtrase/UpdateDateExtrase"
GET_TERT = "ImportExtrase/GetDetaliiTert"
SET_TIP = "ImportExtrase/SetTipOperatie"
UPDATE_EXTRASE_DET = "ImportExtrase/UpdateDateExtraseDet"
ACCEPT_PATH = "ImportExtrase/AcceptImportExtrase"
CHECK_PATH = "ImportExtrase/CheckInregistrariExistente"

UNMAPPED_CONT = "581"
MAX_XML_BYTES = saga_import_date.MAX_XML_BYTES
FILENAME_RE = re.compile(r"^[IP]_\d{2}_\d{2}_\d{4}\.xml$", re.IGNORECASE)
SAMPLE_LIMIT = 12


def import_incasari_xml(
    xml_path: str,
    *,
    confirm_write: bool = False,
    partner: str = "",
    account: str = "",
    asociere: bool = True,
) -> dict[str, Any]:
    preview = preview_incasari_xml(xml_path, partner=partner, account=account, asociere=asociere)
    if not preview.get("ok"):
        return preview
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "import_incasari_xml",
            "preview": preview,
            "details": (
                "Preview only — this will upload the XML on Jurnal de Bancă "
                f"({preview.get('import_url')}), map the treasury account"
                + (f" and partner '{preview.get('partner')}'" if preview.get("partner") else "")
                + (", associate each receipt to unpaid Ieșiri/Intrări" if asociere else "")
                + ", then Accept. Ask the user to confirm, then call again with confirm_write=true."
            ),
        }

    def _run(browser_page):
        page = saga_partners._ready(browser_page)
        source = Path(preview["resolved_path"])
        opened = _open_jurnal(page)
        if not opened.get("ok"):
            return {"ok": False, **opened, "preview": preview}

        saga_session.clear_capture()
        _post(page, CLEAR_CACHE_PATH, form={})

        partner_info = None
        partner_query = str(preview.get("partner") or "").strip()
        if partner_query:
            partner_info = _resolve_partner(page, partner_query, tip=preview.get("default_tip") or "I")
            if not partner_info.get("ok"):
                return {
                    "ok": False,
                    **partner_info,
                    "url": page.url,
                    "screenshot_path": saga_session._save_screenshot(page, "saga-importextrase-partner.png"),
                    "preview": preview,
                }

        uploaded = _upload_xml(page, source)
        if not uploaded.get("ok"):
            return {
                "ok": False,
                **uploaded,
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, "saga-importextrase-upload-failed.png"),
                "capture_path": saga_session._dump_capture("network-importextrase-upload.json"),
                "preview": preview,
            }

        opened_import = _open_importextrase(page)
        if not opened_import.get("ok"):
            return {"ok": False, **opened_import, "upload": uploaded, "preview": preview}

        check = _check_existing(page)
        rows = _list_extrase(page)
        if not rows:
            return {
                "ok": False,
                "error": "Upload succeeded but Import extrase has no rows.",
                "upload": uploaded,
                "check": check,
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, "saga-importextrase-empty.png"),
                "preview": preview,
            }

        account_value = str(preview.get("account") or "").strip()
        xml_by_key = preview.get("lines_by_key") or {}
        updated_cont = _apply_accounts(page, rows, xml_by_key, account_value)
        updated_tert = 0
        if partner_info:
            updated_tert = _apply_partner(page, rows, partner_info)
        elif asociere:
            updated_tert, _resolved = _apply_partners_from_documents(
                page,
                rows,
                xml_by_key,
                tip=str(preview.get("default_tip") or "I"),
            )

        rows = _list_extrase(page)
        associated = 0
        asociere_result: dict[str, Any] = {}
        if asociere:
            asociere_result = _click_asociere_automata(page, rows)
            associated = int(asociere_result.get("associated_count") or 0)

        accepted = _accept_import(page)
        screenshot = saga_session._save_screenshot(page, "saga-importextrase-accept.png")
        capture = saga_session._dump_capture("network-importextrase.json")
        accepted_ok = bool(accepted.get("ok"))
        return {
            "ok": accepted_ok,
            "imported": accepted_ok,
            "filename": source.name,
            "row_count": len(rows),
            "updated_cont": updated_cont,
            "updated_tert": updated_tert,
            "associated_count": associated,
            "asociere_result": asociere_result,
            "partner": (partner_info or {}).get("denumire") if partner_info else "",
            "account": account_value,
            "asociere": asociere,
            "check": check,
            "accept": accepted,
            "upload": uploaded,
            "url": page.url,
            "screenshot_path": screenshot,
            "capture_path": capture,
            "preview": {
                "path": preview.get("path"),
                "filename": preview.get("filename"),
                "line_count": preview.get("line_count"),
                "total_amount": preview.get("total_amount"),
            },
            "error": None if accepted_ok else accepted.get("error") or "Accept Import extrase failed.",
        }

    return saga_session.run_in_session(_run)


def preview_incasari_xml(
    xml_path: str,
    *,
    partner: str = "",
    account: str = "",
    asociere: bool = True,
) -> dict[str, Any]:
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
        summary = summarize_incasari_xml(source)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"Invalid XML: {exc}", "path": str(source)}

    kind = str(summary.get("kind") or "")
    if kind not in {"Incasari", "Plati"}:
        extra = ""
        if kind == "Facturi":
            extra = (
                " Use saga_import_iesiri_xml for RON sales Ieșiri, "
                "or saga_import_xml for purchases on Import date."
            )
        return {
            "ok": False,
            "error": (
                f"{source.name} root <{kind or 'unknown'}> is not a SAGA Încasări/Plăți XML."
                + extra
            ),
            "path": saga_import_date._host(source),
            "filename": source.name,
        }

    warnings: list[str] = []
    if not FILENAME_RE.match(source.name):
        prefix = "I_" if kind == "Incasari" else "P_"
        warnings.append(
            f"SAGA expects {prefix}<dd>_<mm>_<yyyy>.xml; this file is named {source.name}."
        )
    if summary.get("line_count", 0) == 0:
        warnings.append("No <Linie> rows found.")
    partner_name = str(partner or "").strip()
    if asociere and not partner_name:
        warnings.append(
            "No partner= given. Each row gets its client/supplier from the unpaid "
            "Ieșiri (încasări) or Intrări (plăți) whose NrDoc matches <FacturaNumar>, "
            "then SAGA associates via DisplayData(codFactura)."
        )

    account_value = str(account or "").strip() or str(summary.get("default_account") or "")
    import_url = f"{saga_session.DEFAULT_APP_BASE_URL}/{JURNAL_ROUTE}"
    return {
        "ok": True,
        "path": saga_import_date._host(source),
        "resolved_path": str(source),
        "filename": source.name,
        "size_bytes": size,
        "kind": kind,
        "default_tip": "I" if kind == "Incasari" else "P",
        "import_url": import_url,
        "importextrase_url": f"{saga_session.DEFAULT_APP_BASE_URL}/{IMPORT_ROUTE}",
        "line_count": summary.get("line_count", 0),
        "total_amount": summary.get("total_amount"),
        "dates": summary.get("dates") or [],
        "accounts": summary.get("accounts") or [],
        "currencies": summary.get("currencies") or [],
        "account": account_value,
        "partner": partner_name,
        "asociere": asociere,
        "lines": summary.get("lines") or [],
        "lines_by_key": summary.get("lines_by_key") or {},
        "warnings": warnings,
        "details": (
            f"Will upload {source.name} ({summary.get('line_count', 0)} "
            f"{'încasări' if kind == 'Incasari' else 'plăți'}, total "
            f"{summary.get('total_amount')}) on Jurnal de Bancă Import, "
            f"set cont {account_value or '(from XML)'}"
            + (f", partner {partner_name}" if partner_name else ", partner from matching Ieșiri/Intrări")
            + (", then associate via SAGA DisplayData(codFactura)" if asociere else "")
            + ", then Accept."
        ),
    }


def summarize_incasari_xml(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    kind = saga_import_date._local(root.tag)
    if kind.casefold() == "incasari":
        kind = "Incasari"
    elif kind.casefold() == "plati":
        kind = "Plati"
    elif kind.casefold() == "facturi":
        kind = "Facturi"
    lines_out: list[dict[str, Any]] = []
    lines_by_key: dict[str, dict[str, Any]] = {}
    dates: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    currencies: Counter[str] = Counter()
    total = 0.0
    for node in saga_import_date._findall(root, "Linie"):
        row = {
            "data": saga_import_date._child_text(node, "Data"),
            "numar": saga_import_date._child_text(node, "Numar"),
            "suma": round(saga_import_date._number(saga_import_date._child_text(node, "Suma")), 2),
            "cont": saga_import_date._child_text(node, "Cont"),
            "explicatie": saga_import_date._child_text(node, "Explicatie"),
            "factura_numar": saga_import_date._child_text(node, "FacturaNumar"),
            "moneda": saga_import_date._child_text(node, "Moneda") or "RON",
        }
        dates[row["data"]] += 1
        if row["cont"]:
            accounts[row["cont"]] += 1
        currencies[row["moneda"]] += 1
        total += float(row["suma"] or 0)
        key = _line_key(row["data"], row["numar"], row["suma"])
        lines_by_key[key] = row
        if len(lines_out) < SAMPLE_LIMIT:
            lines_out.append(row)
    default_account = accounts.most_common(1)[0][0] if accounts else ""
    return {
        "kind": kind,
        "line_count": sum(dates.values()) if dates else len(saga_import_date._findall(root, "Linie")),
        "total_amount": round(total, 2),
        "dates": [{"date": key, "count": count} for key, count in dates.most_common()],
        "accounts": [{"account": key, "count": count} for key, count in accounts.most_common()],
        "currencies": [{"currency": key, "count": count} for key, count in currencies.most_common()],
        "default_account": default_account,
        "lines": lines_out,
        "lines_by_key": lines_by_key,
    }


def _open_jurnal(page) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", JURNAL_ROUTE)
    if "/sagac/jurnaldebanca" in (page.url or "").casefold():
        return {"ok": True, "url": page.url, "via": "current"}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not open Jurnal de Bancă at {url}: {exc}",
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-jurnal-banca-missing.png"),
        }
    page.wait_for_timeout(1_500)
    return {"ok": True, "url": page.url, "via": "route"}


def _open_importextrase(page) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", IMPORT_ROUTE)
    if "/sagac/importextrase" in (page.url or "").casefold():
        page.wait_for_timeout(1_000)
        return {"ok": True, "url": page.url, "via": "current"}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not open Import extrase at {url}: {exc}",
            "url": page.url,
        }
    page.wait_for_timeout(2_000)
    if "/sagac/importextrase" not in (page.url or "").casefold():
        return {
            "ok": False,
            "error": (
                "SAGA did not stay on Import extrase after upload. "
                "The XML may have been rejected, or the Jurnal de Bancă session expired."
            ),
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-importextrase-missing.png"),
        }
    return {"ok": True, "url": page.url, "via": "route"}


def _upload_xml(page, xml_path: Path) -> dict[str, Any]:
    absolute = saga_import_date._abs(page, UPLOAD_PATH)
    try:
        response = page.request.post(
            absolute,
            multipart={
                "file": {
                    "name": xml_path.name,
                    "mimeType": "text/xml",
                    "buffer": xml_path.read_bytes(),
                }
            },
            headers=saga_session._auth_headers(page),
            timeout=120_000,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"IncarcaExtras failed: {exc}", "endpoint": absolute}
    parsed = saga_import_date._parse_body(response)
    if isinstance(parsed, dict) and parsed.get("success") is True:
        return {"ok": True, "via": "api", "endpoint": absolute, "status": response.status, "response": parsed}
    message = ""
    if isinstance(parsed, dict):
        message = str(parsed.get("message") or "").strip()
    return {
        "ok": False,
        "error": message or "SAGA rejected the XML upload on Jurnal de Bancă.",
        "via": "api",
        "endpoint": absolute,
        "status": response.status,
        "response": parsed,
    }


def _list_extrase(page) -> list[dict[str, Any]]:
    result = _get(page, GET_EXTRASE, params={"RequestSetup": _request_setup()})
    return _rows(result.get("response"))


def _apply_accounts(
    page,
    rows: list[dict[str, Any]],
    xml_by_key: dict[str, dict[str, Any]],
    account: str,
) -> int:
    updated = 0
    for row in rows:
        current = _row_get(row, "cont")
        wanted = account
        xml_row = xml_by_key.get(_extras_key(row))
        if not wanted and xml_row:
            wanted = str(xml_row.get("cont") or "").strip()
        if not wanted or current == wanted:
            continue
        if current and current != UNMAPPED_CONT and not account:
            continue
        extras_id = _row_get(row, "id")
        if not extras_id:
            continue
        _post(page, UPDATE_EXTRASE, form={"coloana": "cont", "valoare": wanted, "id": extras_id})
        updated += 1
    return updated


def _apply_partners_from_documents(
    page,
    rows: list[dict[str, Any]],
    xml_by_key: dict[str, dict[str, Any]],
    *,
    tip: str,
) -> tuple[int, dict[str, dict[str, str]]]:
    index = _document_index(page, tip=tip)
    updated = 0
    resolved: dict[str, dict[str, str]] = {}
    for row in rows:
        extras_id = _row_get(row, "id")
        if not extras_id:
            continue
        xml_row = xml_by_key.get(_extras_key(row)) or {}
        nr = str(xml_row.get("factura_numar") or _row_get(row, "nrDocument") or "").strip()
        invoice = index.get(_norm(nr)) if nr else None
        if not invoice or not invoice.get("client"):
            continue
        _set_extras_partner(
            page,
            extras_id,
            denumire=invoice["client"],
            cod=invoice.get("cod") or "",
            tip=tip,
        )
        updated += 1
        resolved[extras_id] = invoice
    return updated, resolved


def _document_index(page, *, tip: str) -> dict[str, dict[str, str]]:
    incasari = (tip or "I").upper().startswith("I")
    path = "Iesiri/GetData_Iesiri" if incasari else "Intrari/GetData_Intrari"
    partner_fields = ("Client", "client") if incasari else ("Furnizor", "furnizor")
    index: dict[str, dict[str, str]] = {}
    skip = 0
    while True:
        result = _get(
            page,
            path,
            params={"RequestSetup": _request_setup(skip=skip, batch_size=500)},
        )
        batch = _rows(result.get("response"))
        for row in batch:
            nr = _row_get(row, "NrDoc", "nrDoc")
            if not nr:
                continue
            index[_norm(nr)] = {
                "nr": nr,
                "client": _row_get(row, *partner_fields),
                "cod": _row_get(row, "Cod", "cod"),
                "neachitat": _row_get(row, "Neachitat", "neachitat"),
                "id": _row_get(row, "ID_Iesire", "ID_Intrare", "Id", "ID", "PK"),
                "data": _row_get(row, "Data", "data"),
                "scadent": _row_get(row, "Scadent", "scadent"),
                "total": _row_get(row, "Total", "total"),
            }
        if len(batch) < 500:
            break
        skip += len(batch)
        if skip > 20_000:
            break
    return index


def _apply_partner(page, rows: list[dict[str, Any]], partner_info: dict[str, Any]) -> int:
    denumire = str(partner_info.get("denumire") or "").strip()
    if not denumire:
        return 0
    updated = 0
    for row in rows:
        extras_id = _row_get(row, "id")
        if not extras_id:
            continue
        _set_extras_partner(
            page,
            extras_id,
            denumire=denumire,
            cod=str(partner_info.get("cod") or ""),
            tip=str(partner_info.get("tip") or "I"),
        )
        updated += 1
    return updated


def _set_extras_partner(
    page, extras_id: str, *, denumire: str, cod: str, tip: str = "I"
) -> None:
    if denumire:
        _post(page, UPDATE_EXTRASE, form={"coloana": "tert", "valoare": denumire, "id": extras_id})
    if cod:
        _post(page, UPDATE_EXTRASE, form={"coloana": "codFactura", "valoare": cod, "id": extras_id})
        tert = _get(page, GET_TERT, params={"cod": cod, "tip": tip or "I", "idExtras": extras_id})
        body = tert.get("response") if isinstance(tert.get("response"), dict) else {}
        if body.get("codTert"):
            _post(
                page,
                UPDATE_EXTRASE,
                form={"coloana": "codFactura", "valoare": str(body.get("codTert")), "id": extras_id},
            )
        if body.get("denumire"):
            _post(
                page,
                UPDATE_EXTRASE,
                form={"coloana": "tert", "valoare": str(body.get("denumire")), "id": extras_id},
            )


def _click_asociere_automata(page, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Associate using SAGA's DisplayData(cod) endpoints, not the toolbar button.

    `#buttonAsociereAutomata` calls GetTableExtraseDet().DisplayData() with no client
    code, so GetData_ImportExtraseDet returns [] on multi-client files. Picking a tert
    in the UI calls DisplayData(codTert) — same as RequestSetup.Id = client code —
    then UpdateDateExtraseDet. Do that per extras row.
    """
    associated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    det_cache: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        extras_id = _row_get(row, "id")
        cod = _row_get(row, "codFactura", "CodFactura")
        tip = _row_get(row, "tip") or "I"
        nr = _row_get(row, "nrDocument", "NrDocument")
        suma = _money(_row_get(row, "suma"))
        if not extras_id or not cod:
            skipped.append(
                {
                    "nr": nr,
                    "extrasId": extras_id,
                    "cod": cod,
                    "reason": "missing_cod_or_id",
                }
            )
            continue
        _post(page, SET_TIP, form={"tip": tip, "idExtras": extras_id})
        cache_key = f"{tip}|{cod}"
        if cache_key not in det_cache:
            det_cache[cache_key] = _list_extrase_det(page, cod)
            if not det_cache[cache_key]:
                det_cache[cache_key] = _documents_as_det(page, tip=tip, cod=cod)
        det = det_cache[cache_key]
        picked = _pick_det_line(det, nr=nr, suma=suma, cod=cod)
        if not picked:
            skipped.append(
                {
                    "nr": nr,
                    "extrasId": extras_id,
                    "cod": cod,
                    "suma": suma,
                    "reason": "no_unpaid_match",
                    "det": len(det),
                }
            )
            continue
        persist = _persist_asociere(
            page,
            extras_id=extras_id,
            tip=tip,
            cod=cod,
            det=det,
            picked=picked,
        )
        if not persist.get("ok"):
            skipped.append(
                {
                    "nr": nr,
                    "extrasId": extras_id,
                    "cod": cod,
                    "reason": persist.get("error") or "UpdateDateExtraseDet failed",
                }
            )
            continue
        id_factura = _row_get(picked, "IdFactura", "idFactura", "ID_Iesire", "ID_Intrare", "Id")
        nr_factura = _row_get(picked, "NrFactura", "nrFactura", "NrDoc", "nrDoc")
        associated.append(
            {
                "nr": nr,
                "extrasId": extras_id,
                "cod": cod,
                "idFactura": id_factura,
                "nrFactura": nr_factura,
                "ok": True,
            }
        )
        det_cache[cache_key] = [
            line
            for line in det
            if _row_get(line, "IdFactura", "idFactura", "ID_Iesire", "ID_Intrare", "Id") != id_factura
        ]
    count = len(associated)
    return {
        "ok": count > 0,
        "associated_count": count,
        "message": f"Au fost asociate {count} pozitii.",
        "via": "saga_displaydata_cod",
        "associated": associated[:25],
        "skipped": skipped[:25],
    }


def _list_extrase_det(page, cod: str) -> list[dict[str, Any]]:
    result = _get(page, GET_EXTRASE_DET, params={"RequestSetup": _request_setup(master_id=cod)})
    return _rows(result.get("response"))


def _documents_as_det(page, *, tip: str, cod: str) -> list[dict[str, Any]]:
    incasari = (tip or "I").upper().startswith("I")
    path = "Iesiri/GetData_Iesiri" if incasari else "Intrari/GetData_Intrari"
    partner_fields = ("Client", "client") if incasari else ("Furnizor", "furnizor")
    id_fields = ("ID_Iesire", "Id", "ID", "PK") if incasari else ("ID_Intrare", "Id", "ID", "PK")
    out: list[dict[str, Any]] = []
    skip = 0
    while True:
        result = _get(
            page,
            path,
            params={"RequestSetup": _request_setup(skip=skip, batch_size=500)},
        )
        batch = _rows(result.get("response"))
        for row in batch:
            if _row_get(row, "Cod", "cod") != cod:
                continue
            unpaid = _money(_row_get(row, "Neachitat", "neachitat"))
            if unpaid == 0:
                continue
            unpaid_text = _fmt_money(unpaid)
            out.append(
                {
                    "Denumire": _row_get(row, *partner_fields),
                    "NrFactura": _row_get(row, "NrDoc", "nrDoc"),
                    "Data": _row_get(row, "Data", "data"),
                    "Scadent": _row_get(row, "Scadent", "scadent"),
                    "Total": _row_get(row, "Total", "total"),
                    "Neachitat": unpaid_text,
                    "Achitat": "0.00",
                    "CodFactura": cod,
                    "NeachitatReal": unpaid_text,
                    "IdExtras": "",
                    "Integral": "0",
                    "IdFactura": _row_get(row, *id_fields),
                    "IP": tip,
                    "TvaI": _row_get(row, "TVAI", "TvaI", "tvai") or "0",
                    "Curs": _row_get(row, "Curs", "curs") or "0",
                    "TVA": _row_get(row, "TVA", "tva") or "0.00",
                    "CodValuta": _row_get(row, "CodValuta", "codValuta") or "",
                }
            )
        if len(batch) < 500:
            break
        skip += len(batch)
        if skip > 20_000:
            break
    return out


def _pick_det_line(
    det: list[dict[str, Any]],
    *,
    nr: str,
    suma: float,
    cod: str,
) -> dict[str, Any] | None:
    numbered: list[dict[str, Any]] = []
    amount: list[dict[str, Any]] = []
    for line in det:
        unpaid = _money(_row_get(line, "Neachitat", "neachitat"))
        paid = _money(_row_get(line, "Achitat", "achitat"))
        line_cod = _row_get(line, "CodFactura", "codFactura")
        nr_fact = _row_get(line, "NrFactura", "nrFactura", "NrDoc", "nrDoc")
        if paid != 0 or unpaid == 0:
            continue
        if line_cod and line_cod != cod:
            continue
        if nr and _norm(nr_fact) == _norm(nr):
            numbered.append(line)
        if unpaid == suma:
            amount.append(line)
    for line in numbered:
        if _money(_row_get(line, "Neachitat", "neachitat")) == suma:
            return line
    return (numbered[0] if numbered else None) or (amount[0] if amount else None)


def _persist_asociere(
    page,
    *,
    extras_id: str,
    tip: str,
    cod: str,
    det: list[dict[str, Any]],
    picked: dict[str, Any],
) -> dict[str, Any]:
    id_factura = _row_get(picked, "IdFactura", "idFactura", "ID_Iesire", "ID_Intrare", "Id")
    if not id_factura:
        return {"ok": False, "error": "Matched invoice has no IdFactura."}
    paid = _money(_row_get(picked, "Neachitat", "neachitat"))
    paid_text = _fmt_money(paid)
    arr: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    suma_achitata = 0.0
    persist_cod = cod
    for line in det:
        line_id = _row_get(line, "IdFactura", "idFactura", "ID_Iesire", "ID_Intrare", "Id")
        is_picked = line_id == id_factura
        item = _det_persist_item(
            line,
            tip=tip,
            extras_id=extras_id if is_picked else _row_get(line, "IdExtras", "idExtras"),
            paid_text=paid_text if is_picked else None,
        )
        suma_achitata += _money(item.get("Achitat"))
        arr.append(item)
        if is_picked:
            current = item
            persist_cod = str(item.get("CodFactura") or cod)
    result = _post(
        page,
        UPDATE_EXTRASE_DET,
        form={
            "idExtras": extras_id,
            "arrDetalii": json.dumps(arr, ensure_ascii=False),
            "idFactura": id_factura,
            "detaliiExtrasCurent": json.dumps(current, ensure_ascii=False),
            "sumaAchitata": _fmt_money(suma_achitata),
            "codFactura": persist_cod,
        },
    )
    parsed = result.get("response")
    if result.get("ok_http") and not (isinstance(parsed, dict) and parsed.get("success") is False):
        return {"ok": True, "response": parsed}
    message = ""
    if isinstance(parsed, dict):
        message = str(parsed.get("message") or parsed.get("error") or "").strip()
    return {
        "ok": False,
        "error": message or "UpdateDateExtraseDet failed.",
        "response": parsed,
    }


def _det_persist_item(
    line: dict[str, Any],
    *,
    tip: str,
    extras_id: str,
    paid_text: str | None,
) -> dict[str, Any]:
    unpaid = _row_get(line, "Neachitat", "neachitat") or "0.00"
    achitat = _row_get(line, "Achitat", "achitat") or "0.00"
    if paid_text is not None:
        achitat = paid_text
        unpaid = "0.00"
    return {
        "Denumire": _row_get(line, "Denumire", "denumire"),
        "NrFactura": _row_get(line, "NrFactura", "nrFactura", "NrDoc", "nrDoc"),
        "Data": _row_get(line, "Data", "data"),
        "Scadent": _row_get(line, "Scadent", "scadent"),
        "Total": _row_get(line, "Total", "total"),
        "Neachitat": unpaid,
        "Achitat": achitat,
        "CodFactura": _row_get(line, "CodFactura", "codFactura") or "",
        "NeachitatReal": paid_text or _row_get(line, "NeachitatReal", "neachitatReal") or unpaid,
        "IdExtras": extras_id,
        "Integral": "1" if paid_text is not None else (_row_get(line, "Integral", "integral") or "0"),
        "IdFactura": _row_get(line, "IdFactura", "idFactura", "ID_Iesire", "ID_Intrare", "Id"),
        "IP": tip,
        "TvaI": _row_get(line, "TvaI", "TVAI", "tvai") or "0",
        "Curs": _row_get(line, "Curs", "curs") or "0",
        "TVA": _row_get(line, "TVA", "tva") or "0.00",
        "CodValuta": _row_get(line, "CodValuta", "codValuta") or "",
    }


def _fmt_money(value: Any) -> str:
    return f"{_money(value):.2f}"


def _dismiss_saga_warning(page) -> None:
    for selector in (
        ".modal.show button:has-text('OK')",
        ".modal.show .btn-primary",
        "#buttonWarningOK",
        "button:has-text('OK')",
    ):
        loc = page.locator(selector)
        try:
            if loc.count() == 0:
                continue
            loc.first.click(timeout=2_000)
            page.wait_for_timeout(300)
            return
        except Exception:
            continue


def _accept_import(page) -> dict[str, Any]:
    uvf: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    for _ in range(4):
        last = _accept_once(page, uvf)
        parsed = last.get("response")
        if isinstance(parsed, dict) and parsed.get("success") is True:
            page.wait_for_timeout(1_500)
            return {"ok": True, **last}
        if not isinstance(parsed, dict):
            break
        flags = parsed.get("validationFlags") or []
        flag = flags[0] if flags and isinstance(flags[0], dict) else {}
        kind = str(flag.get("type") or "")
        if kind == "CriticalChoice":
            uvf = _merge_uvf(parsed, flag, yes=True)
            continue
        if kind == "Warning":
            return {
                "ok": False,
                "error": str(flag.get("message") or parsed.get("message") or "SAGA warning on Accept."),
                **last,
            }
        if kind == "Error" or parsed.get("success") is False:
            return {
                "ok": False,
                "error": str(
                    flag.get("message") or parsed.get("message") or "Accept Import extrase failed."
                ),
                **last,
            }
        break
    return {
        "ok": False,
        "error": "Accept Import extrase did not return success.",
        **last,
    }


def _accept_once(page, uvf: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"uvf": json.dumps(uvf, ensure_ascii=False)} if uvf else {}
    get_result = _get(page, ACCEPT_PATH, params=payload or None, timeout=180_000)
    parsed = get_result.get("response")
    if get_result.get("ok_http") and isinstance(parsed, dict) and "success" in parsed:
        return get_result
    post_result = _post(page, ACCEPT_PATH, form=payload, timeout=180_000)
    if post_result.get("ok_http"):
        return post_result
    return get_result if get_result.get("ok_http") else post_result


def _check_existing(page) -> dict[str, Any]:
    last = _get(page, CHECK_PATH, timeout=60_000)
    parsed = last.get("response")
    if isinstance(parsed, dict) and parsed.get("success") is True:
        return {"ok": True, "message": parsed.get("message"), "response": parsed}
    if isinstance(parsed, dict):
        flags = parsed.get("validationFlags") or []
        flag = flags[0] if flags and isinstance(flags[0], dict) else {}
        if str(flag.get("type") or "") == "CriticalChoice":
            uvf = _merge_uvf(parsed, flag, yes=True)
            last = _get(page, CHECK_PATH, params={"uvf": json.dumps(uvf, ensure_ascii=False)})
            parsed = last.get("response")
            if isinstance(parsed, dict) and parsed.get("success") is True:
                return {
                    "ok": True,
                    "message": parsed.get("message"),
                    "response": parsed,
                    "accepted_duplicates": True,
                }
        return {
            "ok": False,
            "error": str(flag.get("message") or parsed.get("message") or "CheckInregistrariExistente failed."),
            "response": parsed,
        }
    return {"ok": last.get("ok_http"), "response": parsed}


def _resolve_partner(page, query: str, *, tip: str) -> dict[str, Any]:
    path = "Clienti/GetData_Clienti" if (tip or "I").upper().startswith("I") else "Furnizori/GetData_Furnizori"
    result = _get(page, path, params={"RequestSetup": _request_setup(batch_size=500)})
    partners = _rows(result.get("response"))
    needle = _norm(query)
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for partner in partners:
        cod = _row_get(partner, "cod", "Cod")
        den = _row_get(partner, "denumire", "Denumire")
        if _norm(cod) == needle or _norm(den) == needle:
            exact.append(partner)
        elif needle and (needle in _norm(cod) or needle in _norm(den)):
            partial.append(partner)
    matches = exact or (partial if len(partial) == 1 else [])
    if not matches:
        return {
            "ok": False,
            "error": f"No exact {'client' if tip == 'I' else 'supplier'} match for '{query}'.",
            "candidates": [
                {"cod": _row_get(p, "cod", "Cod"), "denumire": _row_get(p, "denumire", "Denumire")}
                for p in (exact or partial)[:10]
            ],
        }
    if len(matches) > 1:
        return {
            "ok": False,
            "error": f"Multiple partners match '{query}'. Pass the exact name or code.",
            "candidates": [
                {"cod": _row_get(p, "cod", "Cod"), "denumire": _row_get(p, "denumire", "Denumire")}
                for p in matches[:10]
            ],
        }
    partner = matches[0]
    info = {
        "ok": True,
        "cod": _row_get(partner, "cod", "Cod"),
        "denumire": _row_get(partner, "denumire", "Denumire"),
        "cif": _row_get(partner, "codFiscal", "CodFiscal", "CUI"),
    }
    tert = _get(page, GET_TERT, params={"cod": info["cod"], "tip": tip})
    body = tert.get("response") if isinstance(tert.get("response"), dict) else {}
    if isinstance(body, dict) and body.get("denumire"):
        info["denumire"] = str(body.get("denumire") or info["denumire"])
        info["cod"] = str(body.get("codTert") or info["cod"])
        info["cif"] = str(body.get("codFiscal") or info["cif"])
        info["analitic"] = str(body.get("analitic") or "")
    return info


def _merge_uvf(parsed: dict[str, Any], flag: dict[str, Any], *, yes: bool) -> list[dict[str, Any]]:
    existing = parsed.get("userValidationFlags")
    flags: list[dict[str, Any]] = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    flag_id = flag.get("id") or flag.get("ID")
    if flag_id:
        found = False
        for item in flags:
            if str(item.get("id") or item.get("ID")) == str(flag_id):
                item["userChoice"] = "Yes" if yes else "No"
                found = True
                break
        if not found:
            flags.append({"id": flag_id, "userChoice": "Yes" if yes else "No"})
    return flags


def _get(page, path: str, *, params: dict[str, Any] | None = None, timeout: int = 60_000) -> dict[str, Any]:
    return saga_import_date._request(page, "GET", path, params=params, timeout=timeout)


def _post(
    page,
    path: str,
    *,
    form: dict[str, Any] | None = None,
    timeout: int = 60_000,
) -> dict[str, Any]:
    return saga_import_date._request(page, "POST", path, form=form, timeout=timeout)


def _request_setup(*, skip: int = 0, batch_size: int = 0, master_id: str | None = None) -> str:
    payload: dict[str, Any] = {
        "FilterSearchType": 1,
        "FilterCaseSensitive": False,
        "FilterCurrentTable": False,
        "Skip": max(skip, 0),
        "BatchSize": max(batch_size, 0),
        "GetRowsCount": False,
    }
    if master_id:
        payload["Id"] = master_id
    return json.dumps(payload, separators=(",", ":"))


def _rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "Data", "rows", "Rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _row_get(row: dict[str, Any], *names: str) -> str:
    lower = {str(key).casefold(): key for key in row}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
        key = lower.get(name.casefold())
        if key is not None and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""


def _extras_key(row: dict[str, Any]) -> str:
    return _line_key(_row_get(row, "data"), _row_get(row, "nrDocument"), _money(_row_get(row, "suma")))


def _line_key(data: Any, numar: Any, suma: Any) -> str:
    amount = suma if isinstance(suma, (int, float)) else _money(str(suma or ""))
    return f"{str(data or '').strip()}|{str(numar or '').strip()}|{amount:.2f}"


def _money(value: Any) -> float:
    text = str(value or "0").replace(" ", "").replace(",", ".")
    try:
        return round(float(text or 0), 2)
    except ValueError:
        return 0.0


def _norm(value: str) -> str:
    return " ".join((value or "").casefold().split())
