"""Combo lookups: `GetData_ComboBox_<selectModel>` with Home redirects."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import schema as saga_schema


# Plan §2.7: some combos are served from Home, not the screen controller.
HOME_FIRST = {
    "conturi",
    "cont",
    "planconturi",
    "proiecte",
    "activitati",
    "centreprofit",
    "gestiuni",
    "tari",
    "judete",
    "localitati",
    "valute",
    "agenti",
    "grupe",
}

DEFAULT_SELECT_MODELS = {
    "tara": "Tari",
    "judet": "Judete",
    "localitate": "Localitati",
    "client": "Clienti",
    "valuta": "Valute",
    "agent": "Agenti",
    "gestiune": "Gestiuni",
    "cont": "Conturi",
    "tip": "Tip_Iesiri",
}


def combo_action_name(select_model: str) -> str:
    name = (select_model or "").strip()
    if not name:
        return ""
    if name.casefold().startswith("getdata_combobox_"):
        return name
    return f"GetData_ComboBox_{name}"


def combo_paths(controller: str, select_model: str) -> list[str]:
    action = combo_action_name(select_model)
    if not action:
        return []
    ctrl = (controller or "Home").strip().strip("/")
    controller_path = f"{ctrl}/{action}"
    home_path = f"Home/{action}"
    if select_model.casefold() in HOME_FIRST:
        ordered = [home_path, controller_path]
    else:
        ordered = [controller_path, home_path]
    out: list[str] = []
    for path in ordered:
        if path not in out:
            out.append(path)
    return out


def resolve_select_model(operation: str, field: str) -> tuple[str, dict[str, Any] | None]:
    """Return (selectModel, column) for a catalog field, or (field, None) if it is already a model name."""
    wanted = (field or "").strip()
    if not wanted:
        return "", None
    columns = saga_schema.column_map(operation)
    if wanted in columns:
        column = columns[wanted]
        model = str(column.get("selectModel") or column.get("select_model") or "").strip()
        if not model and (column.get("kind") or "").casefold() == "combo":
            model = DEFAULT_SELECT_MODELS.get(wanted.casefold(), wanted)
        return model or wanted, column
    lowered = saga_schema.normalize_key(wanted)
    for name, column in columns.items():
        aliases = [saga_schema.normalize_key(name), *(saga_schema.normalize_key(str(a)) for a in (column.get("aliases") or ()))]
        if lowered in aliases:
            model = str(column.get("selectModel") or "").strip()
            if not model and (column.get("kind") or "").casefold() == "combo":
                model = DEFAULT_SELECT_MODELS.get(name.casefold(), name)
            return model or name, column
    return wanted, None


def lookups_for_screen(operation: str) -> list[dict[str, Any]]:
    spec = saga_registry.require_screen(operation)
    items: list[dict[str, Any]] = []
    for column in saga_schema.catalog_for(spec.schema_id).get("columns") or []:
        if not isinstance(column, dict) or column.get("expose") is False:
            continue
        kind = str(column.get("kind") or column.get("inputType") or "").casefold()
        model = str(column.get("selectModel") or "").strip()
        name = str(column.get("name") or "").strip()
        if not model and kind != "combo":
            continue
        if not model:
            model = DEFAULT_SELECT_MODELS.get(name.casefold(), name)
        items.append(
            {
                "field": name,
                "select_model": model,
                "kind": kind or "combo",
                "paths": combo_paths(spec.route, model),
            }
        )
    return items


def lookup(
    screen: str,
    field: str,
    *,
    query: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    spec = saga_registry.get_screen(screen)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown screen '{screen}'.",
            "screens": saga_registry.list_operation_ids(),
        }
    model, column = resolve_select_model(spec.schema_id, field)
    if not model:
        return {"ok": False, "error": "field is required (catalog column or selectModel name)."}
    paths = combo_paths(spec.route, model)

    def _run(browser_page):
        from markus_mcp.tools.saga import grid as saga_grid
        from markus_mcp.tools.saga import partners as saga_partners
        from markus_mcp.tools.saga import protocol as saga_protocol
        from markus_mcp.tools.saga import session as saga_session

        page = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(page, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        saga_session.clear_capture()
        last: dict[str, Any] = {"ok": False, "error": "Lookup endpoint failed."}
        params = {"Filter": query or ""}
        for path in paths:
            probed = saga_protocol.get_json(page, path, params=params)
            if not probed or not probed.get("ok"):
                last = probed or last
                continue
            body = probed.get("body")
            if not isinstance(body, (dict, list)):
                last = {**(probed or {}), "ok": False, "error": "Combo endpoint did not return JSON."}
                continue
            rows = saga_protocol.rows_from_payload(body)
            if query:
                needle = saga_schema.normalize_key(query)
                rows = [
                    row
                    for row in rows
                    if needle in saga_schema.normalize_key(str(row))
                ]
            cap = max(int(limit or 50), 1)
            return {
                "ok": True,
                "screen": spec.operation,
                "field": field,
                "select_model": model,
                "endpoint": probed.get("endpoint"),
                "count": min(len(rows), cap),
                "total": len(rows),
                "options": rows[:cap],
                "column": {"name": (column or {}).get("name"), "kind": (column or {}).get("kind")},
                "tried": paths,
                "url": page.url,
            }
        return {
            "ok": False,
            "error": last.get("error") or last.get("raw") or "No combo endpoint returned JSON.",
            "screen": spec.operation,
            "field": field,
            "select_model": model,
            "tried": paths,
            "last": last,
        }

    from markus_mcp.tools.saga import session as saga_session

    return saga_session.run_in_session(_run)
