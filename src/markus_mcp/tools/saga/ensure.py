"""Resolve an existing Clienți / Furnizori row. Does not invent a partner."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry


def partner_query(header: dict[str, Any], *, purchase: bool) -> str:
    if purchase:
        return str(header.get("Cod") or header.get("Furnizor") or header.get("FurnizorNume") or "").strip()
    return str(header.get("Cod") or header.get("Client") or header.get("ClientNume") or "").strip()


def preview_note(header: dict[str, Any], *, purchase: bool) -> dict[str, Any]:
    query = partner_query(header, purchase=purchase)
    role = "furnizori" if purchase else "clienti"
    return {
        "role": role,
        "query": query,
        "note": (
            f"On confirm, will search {role} for {query or '(empty)'}. "
            "Missing partner aborts — create it first with the named partner/supplier tool. "
            "This adapter does not auto-create."
        ),
    }


def resolve_on_page(page, header: dict[str, str], *, purchase: bool) -> dict[str, Any]:
    """Fill Cod + name from an existing row. Call inside an open session (do not nest)."""
    query = partner_query(header, purchase=purchase)
    operation = "furnizori" if purchase else "clienti"
    name_field = "Furnizor" if purchase else "Client"
    if header.get("Cod") and header.get(name_field):
        return {
            "ok": True,
            "header": dict(header),
            "matched": {"Cod": header.get("Cod"), name_field: header.get(name_field)},
        }
    if not query:
        return {"ok": False, "error": f"{name_field} or Cod is required."}
    spec = saga_registry.require_screen(operation)
    opened = saga_grid.open_screen(page, spec.route)
    if not opened.get("ok"):
        return {"ok": False, **opened}
    fetched = saga_grid.SagaGrid.for_operation(operation).list(page, skip=0, batch_size=80, keyword=query)
    rows = fetched.get("rows") or []
    exact: list[dict[str, Any]] = []
    q = query.casefold()
    for row in rows:
        cod = str(saga_protocol.row_get(row, "Cod", "cod") or "").strip()
        den = str(saga_protocol.row_get(row, "Denumire", "denumire") or "").strip()
        if cod.casefold() == q or den.casefold() == q:
            exact.append(row)
    pick = exact[0] if len(exact) == 1 else (rows[0] if len(rows) == 1 else None)
    if pick is None:
        return {
            "ok": False,
            "error": (
                f"No unique {spec.title} match for '{query}'. "
                f"Create the {'supplier' if purchase else 'client'} first, then retry."
            ),
            "matches": len(rows),
        }
    out = dict(header)
    out["Cod"] = str(saga_protocol.row_get(pick, "Cod", "cod") or out.get("Cod") or "").strip()
    out[name_field] = str(saga_protocol.row_get(pick, "Denumire", "denumire") or out.get(name_field) or "").strip()
    return {"ok": True, "header": out, "matched": {"Cod": out["Cod"], name_field: out[name_field]}}
