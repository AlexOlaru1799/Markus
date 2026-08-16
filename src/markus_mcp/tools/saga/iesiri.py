"""Create SAGA Ieșiri (RON sales) from a Facturi XML."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from markus_mcp.tools.saga import import_date as saga_import_date
from markus_mcp.tools.saga import invoices as saga_invoices
from markus_mcp.tools.saga import partners as saga_partners
from markus_mcp.tools.saga import session as saga_session
from markus_mcp.tools.saga.documents.parse_facturi_xml import parse_facturi_xml


ROUTE = "Iesiri"
DEFAULT_CONT = "704"
SAMPLE_LIMIT = 25


def import_iesiri_xml(xml_path: str, *, confirm_write: bool = False) -> dict[str, Any]:
    preview = preview_iesiri_xml(xml_path)
    if not preview.get("ok"):
        return preview
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "import_iesiri_xml",
            "preview": _public_preview(preview),
            "details": (
                "Preview only — this will create RON Ieșiri "
                f"({preview.get('invoice_count', 0)} invoice(s)) from {preview.get('filename')}. "
                "Existing NrDoc values are skipped. Ask the user to confirm, then call "
                "again with confirm_write=true."
            ),
        }

    def _run(browser_page):
        page = saga_partners._ready(browser_page)
        opened = _open_iesiri(page)
        if not opened.get("ok"):
            return {"ok": False, **opened, "preview": preview}

        saga_session.clear_capture()
        existing = {_row_nr(row) for row in _list_iesiri(page)}
        documents = list(preview.get("documents") or [])
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        if not documents:
            for invoice in preview.get("parsed") or []:
                documents.append(
                    {
                        "header": {
                            "NrDoc": invoice.get("number"),
                            "Data": invoice.get("date"),
                            "Scadent": invoice.get("scadent") or invoice.get("date"),
                            "Cod": invoice.get("cod"),
                            "Client": invoice.get("client"),
                        },
                        "lines": [
                            {
                                "Denumire": line.get("descriere"),
                                "Cantitate": line.get("cantitate"),
                                "PretUnitar": line.get("pret") or line.get("valoare"),
                                "Valoare": line.get("valoare"),
                                "TVA": line.get("tva"),
                                "TVA_ART": line.get("tva_proc"),
                                "Cont": line.get("cont") or DEFAULT_CONT,
                                "Cod": line.get("cod"),
                            }
                            for line in (invoice.get("lines") or [])
                        ],
                    }
                )

        for document in documents:
            header = document.get("header") or {}
            nr = str(header.get("NrDoc") or "").strip()
            if nr and nr in existing:
                skipped.append({"number": nr, "reason": "NrDoc already exists on Ieșiri"})
                continue
            result = saga_invoices.post_on_page(
                page,
                "iesiri",
                {str(k): str(v) for k, v in header.items() if v not in (None, "")},
                [
                    {str(k): str(v) for k, v in line.items() if v not in (None, "")}
                    for line in (document.get("lines") or [])
                    if isinstance(line, dict)
                ],
            )
            if result.get("ok"):
                created.append(result)
                if nr:
                    existing.add(nr)
            else:
                failed.append(result)

        listed = _list_iesiri(page)
        created_nrs = {item.get("number") for item in created}
        verified = [
            {
                "NrDoc": _row_nr(row),
                "Client": _row_get(row, "Client"),
                "Total": _row_get(row, "Total"),
                "Neachitat": _row_get(row, "Neachitat"),
            }
            for row in listed
            if _row_nr(row) in created_nrs
        ]
        ok = bool(created) and not failed
        return {
            "ok": ok,
            "imported": ok or bool(created),
            "created_count": len(created),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "created": created[:SAMPLE_LIMIT],
            "skipped": skipped[:SAMPLE_LIMIT],
            "failed": failed[:SAMPLE_LIMIT],
            "verified": verified[:SAMPLE_LIMIT],
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-import-iesiri.png"),
            "capture_path": saga_session._dump_capture("network-import-iesiri.json"),
            "preview": _public_preview(preview),
            "error": None
            if not failed
            else f"{len(failed)} invoice(s) failed to create. See failed.",
        }

    return saga_session.run_in_session(_run)


def preview_iesiri_xml(xml_path: str) -> dict[str, Any]:
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
    if size > saga_import_date.MAX_XML_BYTES:
        return {"ok": False, "error": f"{source.name} is larger than 25 MB."}

    try:
        parsed = parse_iesiri_xml(source)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"Invalid XML: {exc}", "path": str(source)}

    kind = parsed.get("kind") or ""
    if kind in {"Incasari", "Plati"}:
        return {
            "ok": False,
            "error": (
                f"{source.name} is a SAGA {kind} XML. "
                "Use saga_import_incasari_xml, not saga_import_iesiri_xml."
            ),
            "tool": "saga_import_incasari_xml",
            "filename": source.name,
        }
    if kind != "Facturi":
        return {
            "ok": False,
            "error": f"{source.name} root <{kind or 'unknown'}> is not a Facturi XML for Ieșiri.",
            "filename": source.name,
        }

    invoices = parsed.get("invoices") or []
    warnings: list[str] = []
    missing_client = [item["number"] for item in invoices if not item.get("client") and not item.get("cod")]
    if missing_client:
        warnings.append(
            "These invoices have no ClientNume/ClientCod: " + ", ".join(missing_client[:10])
        )
    if any(item.get("currency", "RON").upper() not in {"", "RON"} for item in invoices):
        warnings.append(
            "Non-RON FacturaMoneda found. This tool writes Ieșiri (RON). "
            "Use saga_add_iesiri_valuta / Import date for FX."
        )
    clients = {item.get("client") for item in invoices if item.get("client")}
    suppliers = {item.get("supplier") for item in invoices if item.get("supplier")}
    if len(clients) <= 1 and len(suppliers) > 1 and not any(item.get("cod") for item in invoices):
        warnings.append(
            "This looks like purchase invoices (many FurnizorNume, one ClientNume). "
            "Use saga_import_xml on Import date, not saga_import_iesiri_xml."
        )

    return {
        "ok": True,
        "path": saga_import_date._host(source),
        "resolved_path": str(source),
        "filename": source.name,
        "size_bytes": size,
        "import_url": f"{saga_session.DEFAULT_APP_BASE_URL}/{ROUTE}",
        "invoice_count": len(invoices),
        "line_count": parsed.get("line_count", 0),
        "total_amount": parsed.get("total_amount"),
        "invoices": [
            {
                "number": item.get("number"),
                "date": item.get("date"),
                "client": item.get("client"),
                "cod": item.get("cod"),
                "amount": item.get("amount"),
                "line_count": len(item.get("lines") or []),
            }
            for item in invoices[:SAMPLE_LIMIT]
        ],
        "parsed": invoices,
        "documents": parsed.get("documents") or [],
        "warnings": warnings,
        "details": (
            f"Will create {len(invoices)} Ieșiri invoice(s) from {source.name} "
            f"(total {parsed.get('total_amount')}). Existing NrDoc values are skipped."
        ),
    }


def parse_iesiri_xml(path: Path) -> dict[str, Any]:
    parsed = parse_facturi_xml(path, operation="iesiri")
    return {
        "kind": parsed.get("kind"),
        "invoices": parsed.get("invoices") or [],
        "documents": parsed.get("documents") or [],
        "line_count": parsed.get("line_count", 0),
        "total_amount": parsed.get("total_amount"),
    }


def _open_iesiri(page) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", ROUTE)
    if "/sagac/iesiri" in (page.url or "").casefold() and "valuta" not in (page.url or "").casefold():
        return {"ok": True, "url": page.url, "via": "current"}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not open Ieșiri at {url}: {exc}",
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-iesiri-missing.png"),
        }
    page.wait_for_timeout(1_200)
    return {"ok": True, "url": page.url, "via": "route"}


def _list_iesiri(page) -> list[dict[str, Any]]:
    from markus_mcp.tools.saga import grid as saga_grid

    fetched = saga_grid.SagaGrid.for_operation("iesiri").list(page, skip=0, batch_size=500)
    return list(fetched.get("rows") or [])


def _create_invoice(page, invoice: dict[str, Any]) -> dict[str, Any]:
    """Thin wrapper: same posting path as saga_add_iesire."""
    header = {
        "NrDoc": str(invoice.get("number") or ""),
        "Data": str(invoice.get("date") or ""),
        "Scadent": str(invoice.get("scadent") or invoice.get("date") or ""),
        "Cod": str(invoice.get("cod") or ""),
        "Client": str(invoice.get("client") or ""),
    }
    lines = []
    for xml_line in invoice.get("lines") or []:
        line = {
            "Denumire": xml_line.get("descriere") or f"Linie {header['NrDoc']}",
            "Cantitate": xml_line.get("cantitate") or "1",
            "PretUnitar": xml_line.get("pret") or xml_line.get("valoare"),
            "Valoare": xml_line.get("valoare") or xml_line.get("pret"),
            "TVA": xml_line.get("tva") or "0",
            "TVA_ART": xml_line.get("tva_proc") or "0",
            "Cont": xml_line.get("cont") or DEFAULT_CONT,
        }
        if xml_line.get("cod"):
            line["Cod"] = xml_line["cod"]
        lines.append({k: str(v) for k, v in line.items() if v not in (None, "")})
    return saga_invoices.post_on_page(
        page,
        "iesiri",
        {k: v for k, v in header.items() if v},
        lines,
    )


def _public_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in preview.items() if key not in {"parsed", "documents"}}


def _row_nr(row: dict[str, Any]) -> str:
    return _row_get(row, "NrDoc", "nrDoc")


def _row_get(row: dict[str, Any], *names: str) -> str:
    lower = {str(key).casefold(): key for key in row}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
        key = lower.get(name.casefold())
        if key is not None and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""
