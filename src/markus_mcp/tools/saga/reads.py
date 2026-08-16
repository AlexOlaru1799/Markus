"""Generic read MCP surface: list / get rows on onboarded grids."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import session as saga_session


def list_rows(
    screen: str,
    *,
    page: int = 1,
    page_size: int = 50,
    query: str | None = None,
    master_id: str | None = None,
) -> dict[str, Any]:
    spec = saga_registry.get_screen(screen)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown screen '{screen}'. Use saga_list_screens.",
            "screens": saga_registry.list_operation_ids(),
        }
    page_n = max(int(page or 1), 1)
    size = max(min(int(page_size or 50), 500), 1)
    skip = (page_n - 1) * size

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        p = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(p, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        client = saga_grid.SagaGrid.for_operation(spec.operation)
        fetched = client.list(
            p,
            skip=skip,
            batch_size=size,
            keyword=(query or None),
            master_id=(str(master_id).strip() or None) if master_id else None,
        )
        if not fetched.get("ok"):
            return {
                "ok": False,
                "error": fetched.get("error") or fetched.get("raw") or "GetData failed.",
                "screen": spec.operation,
                "endpoint": fetched.get("endpoint"),
                "url": p.url,
            }
        rows = fetched.get("rows") or []
        total = fetched.get("rows_count")
        if total is None:
            total = skip + len(rows)
            if len(rows) == size:
                total = None
        return {
            "ok": True,
            "screen": spec.operation,
            "table": spec.table,
            "primary_key": spec.pk,
            "page": page_n,
            "page_size": size,
            "count": len(rows),
            "total": total,
            "query": query or "",
            "master_id": master_id or "",
            "endpoint": fetched.get("endpoint"),
            "rows": rows,
            "url": p.url,
        }

    return saga_session.run_in_session(_run)


def get_row(screen: str, pk: str, *, with_details: bool = True) -> dict[str, Any]:
    spec = saga_registry.get_screen(screen)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown screen '{screen}'. Use saga_list_screens.",
            "screens": saga_registry.list_operation_ids(),
        }
    key = (pk or "").strip()
    if not key:
        return {"ok": False, "error": "pk cannot be empty."}

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        p = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(p, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        client = saga_grid.SagaGrid.for_operation(spec.operation)
        row = client.get(p, key)
        if row is None:
            return {
                "ok": False,
                "error": f"No row matched pk '{key}' on {spec.operation}.",
                "screen": spec.operation,
                "primary_key": spec.pk,
                "url": p.url,
            }
        payload: dict[str, Any] = {
            "ok": True,
            "screen": spec.operation,
            "table": spec.table,
            "primary_key": spec.pk,
            "pk": saga_protocol.row_get(row, spec.pk, "Id", "ID", "Cod", "PK") or key,
            "row": row,
            "url": p.url,
        }
        if with_details and spec.detail_operation:
            parent = payload["pk"]
            details = client.details(p, parent, spec.detail_operation)
            payload["details"] = details.get("rows") or []
            payload["detail_operation"] = spec.detail_operation
            payload["detail_count"] = len(payload["details"])
        return payload

    return saga_session.run_in_session(_run)
