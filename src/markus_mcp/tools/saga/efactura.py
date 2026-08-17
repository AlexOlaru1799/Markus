"""e-Factura list/download. ANAF submit/cancel/token stay human-gated."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.saga import exports as saga_exports
from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import reads as saga_reads
from markus_mcp.tools.saga import session as saga_session


ROUTES = ("EFactura", "ImportEFactura", "ImportEFacturiPrimite")
LIST_PATHS = (
    "EFactura/LoadFacturiImport",
    "EFactura/GetData_EFactura",
    "ImportEFactura/GetData_ImportEFactura",
    "ImportEFacturiPrimite/GetData_ImportEFacturiPrimite",
)
DOWNLOAD_PATHS = (
    "EFactura/DescarcaXML",
    "EFactura/DownloadXML",
    "EFactura/GetXML",
    "EFactura/DescarcaFactura",
)
SUBMIT_PATHS = (
    "EFactura/TrimiteEFactura",
    "EFactura/Transmite",
    "EFactura/ImportEFactura",
)
CANCEL_PATHS = ("EFactura/AnulareEFactura",)
TOKEN_READ = "EFactura/ReadToken"
SAMPLE_LIMIT = 50


def _host(path: Path) -> str:
    try:
        return str(host_data_dir() / path.relative_to(data_dir()))
    except ValueError:
        return str(path)


def _row_get(row: dict[str, Any], *names: str) -> str:
    lower = {str(key).casefold(): key for key in row}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
        key = lower.get(name.casefold())
        if key is not None and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""


def _public_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _row_get(row, "Id", "ID_EFACT", "id_efact", "Index"),
        "number": _row_get(row, "NrDoc", "FacturaNumar", "Numar"),
        "date": _row_get(row, "Data"),
        "partner": _row_get(row, "Denumire", "Client", "Furnizor"),
        "cif": _row_get(row, "CIF", "CodFiscal", "CUI"),
        "index": _row_get(row, "Index", "IndexIncarcare"),
        "status": _row_get(row, "Stare", "Status"),
        "kind": _row_get(row, "Tip"),
        "total": _row_get(row, "Total", "Valoare"),
    }


def list_invoices(*, query: str | None = None, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """List e-Factura rows. Does not submit or import."""
    listed = saga_reads.list_rows(
        "efactura",
        page=page,
        page_size=page_size,
        query=query,
    )
    if listed.get("ok"):
        rows = listed.get("rows") or []
        listed["invoices"] = [_public_row(row) for row in rows[:SAMPLE_LIMIT]]
        listed["details"] = (
            "Read-only list. Do not call saga_efactura_submit or saga_efactura_cancel "
            "unless the user explicitly asked and confirmed. SAGA WEB may only expose "
            "issued invoices; inbound import may still be desktop-only."
        )
        return listed

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page_obj = saga_partners._ready(browser_page)
        opened = None
        for route in ROUTES:
            opened = saga_grid.open_screen(page_obj, route)
            if opened.get("ok"):
                break
        if not opened or not opened.get("ok"):
            return {
                "ok": False,
                "error": (
                    "Could not open an e-Factura screen. SAGA WEB may not have migrated "
                    "inbound import yet (issued send only)."
                ),
                "tried_routes": list(ROUTES),
                "url": page_obj.url,
                "screenshot_path": saga_session._save_screenshot(page_obj, "saga-efactura-missing.png"),
            }
        client = saga_grid.SagaGrid.for_operation("efactura")
        fetched = client.list(page_obj, skip=max(int(page or 1) - 1, 0) * max(int(page_size or 50), 1), batch_size=page_size)
        rows = fetched.get("rows") or []
        return {
            "ok": bool(fetched.get("ok")),
            "screen": "efactura",
            "count": len(rows),
            "invoices": [_public_row(row) for row in rows[:SAMPLE_LIMIT]],
            "rows": rows[:SAMPLE_LIMIT],
            "endpoint": fetched.get("endpoint"),
            "url": page_obj.url,
            "error": None if fetched.get("ok") else (fetched.get("error") or "LoadFacturiImport failed."),
        }

    return saga_session.run_in_session(_run)


def download_invoice(invoice_id: str) -> dict[str, Any]:
    key = (invoice_id or "").strip()
    if not key:
        return {"ok": False, "error": "invoice_id is required (Id / Index / NrDoc)."}

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page_obj = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(page_obj, "EFactura")
        if not opened.get("ok"):
            opened = saga_grid.open_screen(page_obj, "ImportEFactura")
        last: dict[str, Any] = {}
        for path in DOWNLOAD_PATHS:
            for params in (
                {"Id": key},
                {"Index": key},
                {"ID_EFACT": key},
                {"NrDoc": key},
            ):
                raw = saga_protocol.fetch_raw(page_obj, "GET", path, params=params)
                last = raw
                body = raw.get("body") or b""
                kind = saga_exports.sniff_bytes(body)
                is_xml = kind == "xml" or body.lstrip().startswith(b"<?xml")
                if raw.get("ok_http") and body and (kind in {"xml", "pdf", "zip"} or is_xml):
                    folder = data_dir() / "saga" / "efactura"
                    folder.mkdir(parents=True, exist_ok=True)
                    ext = "xml" if is_xml else (kind or "bin")
                    dest = folder / f"efactura_{key}.{ext}"
                    dest.write_bytes(bytes(body))
                    return {
                        "ok": True,
                        "invoice_id": key,
                        "path": _host(dest),
                        "resolved_path": str(dest),
                        "bytes": dest.stat().st_size,
                        "endpoint": raw.get("endpoint"),
                    }
        return {
            "ok": False,
            "error": "Could not download e-Factura XML/PDF. Endpoint may not exist on this WEB build.",
            "invoice_id": key,
            "last_status": last.get("status"),
            "last_endpoint": last.get("endpoint"),
            "url": page_obj.url,
        }

    return saga_session.run_in_session(_run)


def token_status() -> dict[str, Any]:
    """Read whether an SPV token is present. Does not return the token value."""

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page_obj = saga_partners._ready(browser_page)
        probed = saga_protocol.ajax(page_obj, "GET", TOKEN_READ)
        body = probed.get("response")
        present = False
        if isinstance(body, dict):
            blob = " ".join(str(value) for value in body.values() if value not in (None, ""))
            present = bool(blob.strip()) and "null" not in blob.casefold()
        elif body not in (None, "", False, 0, "0"):
            present = True
        return {
            "ok": bool(probed.get("ok_http")),
            "token_present": present,
            "endpoint": probed.get("endpoint"),
            "details": "Token value is not returned. SaveToken stays human-gated.",
        }

    return saga_session.run_in_session(_run)


def _gated(
    *,
    action: str,
    paths: tuple[str, ...],
    invoice_id: str,
    confirm_write: bool,
    confirm_phrase: str,
    expected_phrase: str,
) -> dict[str, Any]:
    key = (invoice_id or "").strip()
    if not key:
        return {"ok": False, "error": "invoice_id is required."}
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": action,
            "preview": {"invoice_id": key, "paths": list(paths)},
            "details": (
                f"HUMAN-GATED. This talks to ANAF/SPV ({action}). "
                f"Only after the user explicitly OK's, call again with confirm_write=true "
                f"and confirm_phrase='{expected_phrase}'."
            ),
        }
    if (confirm_phrase or "").strip() != expected_phrase:
        return {
            "ok": False,
            "error": f"confirm_phrase must be exactly '{expected_phrase}'. Refusing unattended {action}.",
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page_obj = saga_partners._ready(browser_page)
        from markus_mcp.tools.saga import context as saga_context

        blocked = saga_context.assert_writable(page_obj, screen="efactura", allow_closed=True)
        if blocked:
            return blocked
        saga_grid.open_screen(page_obj, "EFactura")
        last: dict[str, Any] = {}
        for path in paths:
            last = saga_protocol.ajax(page_obj, "POST", path, form={"Id": key, "Index": key})
            if last.get("ok_http"):
                return {
                    "ok": True,
                    "action": action,
                    "invoice_id": key,
                    "endpoint": last.get("endpoint"),
                    "response": last.get("response"),
                    "url": page_obj.url,
                    "screenshot_path": saga_session._save_screenshot(page_obj, f"saga-efactura-{action}.png"),
                }
        return {
            "ok": False,
            "error": f"{action} endpoint did not succeed on this WEB build.",
            "last_status": last.get("status"),
            "last_endpoint": last.get("endpoint"),
            "url": page_obj.url,
        }

    return saga_session.run_in_session(_run)


def submit_invoice(invoice_id: str, *, confirm_write: bool = False, confirm_phrase: str = "") -> dict[str, Any]:
    return _gated(
        action="efactura_submit",
        paths=SUBMIT_PATHS,
        invoice_id=invoice_id,
        confirm_write=confirm_write,
        confirm_phrase=confirm_phrase,
        expected_phrase="TRIMITE EFACTURA",
    )


def cancel_invoice(invoice_id: str, *, confirm_write: bool = False, confirm_phrase: str = "") -> dict[str, Any]:
    return _gated(
        action="efactura_cancel",
        paths=CANCEL_PATHS,
        invoice_id=invoice_id,
        confirm_write=confirm_write,
        confirm_phrase=confirm_phrase,
        expected_phrase="ANULEAZA EFACTURA",
    )
