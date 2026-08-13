from __future__ import annotations

from typing import Any

from markus_mcp.paths import data_dir
from markus_mcp.tools.smartbill import cloud
from markus_mcp.tools.smartbill.dates import resolve_range
from markus_mcp.tools.smartbill.saga_xml import convert_xls_to_saga_xml


def list_supplier_invoices(
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
    section: str = "all",
    limit: int = 200,
) -> dict[str, Any]:
    start, end = resolve_range(date_from, date_to, period)
    return cloud.list_invoices(start, end, section=section, limit=limit)


def export_supplier_invoices_xls(
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
    section: str = "all",
) -> dict[str, Any]:
    start, end = resolve_range(date_from, date_to, period)
    dest = data_dir() / "smartbill" / f"Facturi-achizitii-{start}-{end}.xls"
    return cloud.export_invoices(start, end, section, dest)


def invoices_to_saga_xml(
    xls_path: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
    section: str = "all",
) -> dict[str, Any]:
    """Convert a Documente furnizori spreadsheet to SAGA Facturi XML.

    If ``xls_path`` is omitted, export the period first, then convert that file.
    """
    if xls_path:
        extra: dict[str, Any] = {}
        if date_from or date_to or period:
            start, end = resolve_range(date_from, date_to, period)
            extra["date_from"] = start
            extra["date_to"] = end
        converted = convert_xls_to_saga_xml(xls_path, date_to=extra.get("date_to") or date_to)
        converted.update(extra)
        return converted
    exported = export_supplier_invoices_xls(
        date_from=date_from,
        date_to=date_to,
        period=period,
        section=section,
    )
    if not exported.get("ok"):
        return exported
    path = exported.get("path")
    if not path:
        return {"ok": False, "error": "Export succeeded but no spreadsheet path was returned."}
    converted = convert_xls_to_saga_xml(path, date_to=exported.get("date_to"))
    converted["xls_path"] = path
    converted["row_count_xls"] = exported.get("row_count")
    converted["date_from"] = exported.get("date_from")
    converted["date_to"] = exported.get("date_to")
    converted["section"] = exported.get("section")
    return converted
