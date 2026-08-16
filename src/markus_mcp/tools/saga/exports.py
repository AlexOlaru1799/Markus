"""Grid Excel export via `Home/ExportDate`. Reject HTML error pages."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import session as saga_session


XLSX_MAGIC = b"PK\x03\x04"
XLS_MAGIC = b"\xd0\xcf\x11\xe0"
PDF_MAGIC = b"%PDF"


def sniff_bytes(body: bytes) -> str | None:
    if not body:
        return None
    if body.startswith(PDF_MAGIC):
        return "pdf"
    if body.startswith(XLSX_MAGIC):
        return "xlsx"
    if body.startswith(XLS_MAGIC):
        return "xls"
    head = body.lstrip()[:400]
    lowered = head.lower()
    if lowered.startswith(b"<?xml") and b"spreadsheet" in lowered:
        return "xls"
    if lowered.startswith(b"<?xml"):
        return "xml"
    if lowered.startswith(b"<html") or b"<html" in lowered[:80] or b"<!doctype html" in lowered:
        return "html"
    if lowered.startswith(b"{") or lowered.startswith(b"["):
        return "json"
    return None


def export_dir() -> Path:
    path = data_dir() / "saga" / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _host(path: Path) -> str:
    try:
        return str(host_data_dir() / path.relative_to(data_dir()))
    except ValueError:
        return str(path)


def export_grid(
    screen: str,
    *,
    query: str | None = None,
    tip: str = "xlsx",
) -> dict[str, Any]:
    spec = saga_registry.get_screen(screen)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown screen '{screen}'.",
            "screens": saga_registry.list_operation_ids(),
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(page, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        saga_session.clear_capture()
        setup = saga_protocol.request_setup(
            skip=0,
            batch_size=0,
            keyword=(query or None),
            get_rows_count=True,
        )
        tips = [tip] if tip else []
        for extra in ("xlsx", "xls", "Excel"):
            if extra not in tips:
                tips.append(extra)
        attempts: list[dict[str, Any]] = []
        for export_tip in tips:
            for rows_export in ("0", "all", ""):
                form = {
                    "TableName": spec.table,
                    "RequestSetup": setup,
                    "Tip": export_tip,
                    "RowsExport": rows_export,
                }
                raw = saga_protocol.fetch_raw(
                    page,
                    "POST",
                    "Home/ExportDate",
                    form=form,
                    timeout=120_000,
                )
                kind = sniff_bytes(raw.get("body") or b"")
                attempts.append(
                    {
                        "tip": export_tip,
                        "rows_export": rows_export,
                        "status": raw.get("status"),
                        "content_type": raw.get("content_type"),
                        "kind": kind,
                        "bytes": len(raw.get("body") or b""),
                    }
                )
                if kind in {"xlsx", "xls"}:
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    filename = f"{spec.operation}-{stamp}.{kind}"
                    dest = export_dir() / filename
                    dest.write_bytes(raw["body"])
                    return {
                        "ok": True,
                        "screen": spec.operation,
                        "table": spec.table,
                        "path": _host(dest),
                        "resolved_path": str(dest),
                        "filename": filename,
                        "kind": kind,
                        "size_bytes": dest.stat().st_size,
                        "endpoint": raw.get("endpoint"),
                        "content_type": raw.get("content_type"),
                        "attempts": attempts,
                        "url": page.url,
                        "capture_path": saga_session._dump_capture("network-export-grid.json"),
                    }
                if kind == "html":
                    continue
        return {
            "ok": False,
            "error": (
                "Home/ExportDate did not return a real xlsx/xls file "
                "(got HTML or JSON). See attempts."
            ),
            "screen": spec.operation,
            "attempts": attempts,
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-export-failed.png"),
            "capture_path": saga_session._dump_capture("network-export-grid.json"),
        }

    return saga_session.run_in_session(_run)
