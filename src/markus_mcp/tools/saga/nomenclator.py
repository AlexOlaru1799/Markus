"""Named master-data writes via SagaGrid + schema. Not a partners.py clone; no generic MCP."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import reads as saga_reads
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga import session as saga_session


def _clean(fields: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (fields or {}).items():
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        out[str(key)] = value
    return out


def _normalize_geo(row: dict[str, str]) -> dict[str, str]:
    from markus_mcp.tools.saga.partners import JUDET_CODES, _normalize

    if "Tara" in row and _normalize(row["Tara"]) in {"romania", "românia", "ro"}:
        row["Tara"] = "RO"
    if "Judet" in row:
        jud = row["Judet"].strip()
        mapped = JUDET_CODES.get(_normalize(jud))
        if mapped:
            row["Judet"] = mapped
        elif len(jud) <= 2:
            row["Judet"] = jud.upper()
    if "Localitate" in row and _normalize(row["Localitate"]) in {"bucuresti", "bucurești"}:
        row["Localitate"] = "BUCURESTI"
    return row


def field_catalog(operation: str) -> dict[str, Any]:
    return saga_schema.describe_screen(operation)


def list_records(
    operation: str,
    *,
    noun: str,
    page: int = 1,
    page_size: int = 50,
    query: str | None = None,
) -> dict[str, Any]:
    result = saga_reads.list_rows(operation, page=page, page_size=page_size, query=query)
    if result.get("ok"):
        result[f"{noun}s"] = result.get("rows") or []
    return result


def get_record(operation: str, pk: str, *, noun: str) -> dict[str, Any]:
    result = saga_reads.get_row(operation, pk, with_details=False)
    if result.get("ok"):
        result[noun] = result.get("row")
    return result


def create_record(
    operation: str,
    fields: dict[str, Any],
    *,
    noun: str,
    confirm_write: bool = False,
    action: str | None = None,
) -> dict[str, Any]:
    spec = saga_registry.get_screen(operation)
    if spec is None:
        return {"ok": False, "error": f"Unknown screen '{operation}'.", "screens": saga_registry.list_operation_ids()}
    payload = _clean(fields)
    catalog = field_catalog(operation)
    if not payload:
        return {"ok": False, "error": "fields cannot be empty.", "writable_fields": catalog.get("fields")}
    mapped = saga_schema.map_fields(operation, payload, required_on_create=True)
    if mapped.unknown:
        return {
            "ok": False,
            "error": f"Unknown field(s): {', '.join(mapped.unknown)}",
            "unknown_fields": mapped.unknown,
            "writable_fields": catalog.get("fields"),
        }
    if mapped.missing_required:
        return {
            "ok": False,
            "error": f"Missing required field(s): {', '.join(mapped.missing_required)}",
            "missing_required": mapped.missing_required,
            "writable_fields": catalog.get("fields"),
        }
    row_data = _normalize_geo(dict(mapped.fields))
    verb = action or f"create_{noun}"
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": verb,
            "preview": payload,
            "mapped_fields": row_data,
            "auto_filled": mapped.auto_filled,
            "details": (
                f"Preview only — only these user-specified fields will be written on {spec.title}. "
                "Ask the user to confirm, then call again with confirm_write=true."
            ),
            "writable_fields": [item["name"] for item in (catalog.get("fields") or [])],
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(page, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        saga_session.clear_capture()
        client = saga_grid.SagaGrid.for_operation(spec.operation)
        if spec.operation == "registru_casa_valuta" and row_data.get("Valuta") and not row_data.get("Curs"):
            from markus_mcp.tools.saga.iesiri_valuta import fetch_last_valuta

            curs = fetch_last_valuta(page, valuta=row_data["Valuta"], data=str(row_data.get("Data") or ""))
            if curs:
                row_data["Curs"] = curs
                mapped.auto_filled["Curs"] = curs
        if spec.pk not in row_data or not row_data.get(spec.pk):
            generated = client.next_index(page)
            if generated:
                row_data[spec.pk] = generated
                mapped.auto_filled[spec.pk] = generated
        result = client.create(page, row_data, allow_choices=True)
        payload_out = result.as_dict()
        verified = client.get(page, row_data.get(spec.pk) or payload_out.get("new_id") or "")
        ok = bool(result.ok)
        return {
            "ok": ok,
            "created": ok,
            "via": "grid",
            "screen": spec.operation,
            "endpoint": payload_out.get("endpoint"),
            "request": payload,
            "row_data": row_data,
            "auto_filled": mapped.auto_filled,
            "response": payload_out.get("response"),
            "outcome": result.outcome,
            noun: verified,
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(
                page, f"saga-{noun}-{'created' if ok else 'create-failed'}.png"
            ),
            "capture_path": saga_session._dump_capture(f"network-{noun}-create.json"),
            "error": None if ok else (result.message or "Create failed."),
        }

    return saga_session.run_in_session(_run)


def update_record(
    operation: str,
    pk: str,
    fields: dict[str, Any],
    *,
    noun: str,
    confirm_write: bool = False,
    action: str | None = None,
) -> dict[str, Any]:
    spec = saga_registry.get_screen(operation)
    if spec is None:
        return {"ok": False, "error": f"Unknown screen '{operation}'."}
    key = (pk or "").strip()
    payload = _clean(fields)
    catalog = field_catalog(operation)
    if not key:
        return {"ok": False, "error": "pk cannot be empty."}
    if not payload:
        return {"ok": False, "error": "fields cannot be empty.", "writable_fields": catalog.get("fields")}
    mapped = saga_schema.map_fields(operation, payload)
    if mapped.unknown:
        return {
            "ok": False,
            "error": f"Unknown field(s): {', '.join(mapped.unknown)}",
            "unknown_fields": mapped.unknown,
            "writable_fields": catalog.get("fields"),
        }
    existing = get_record(operation, key, noun=noun)
    if not existing.get("ok"):
        return existing
    updates = _normalize_geo(dict(mapped.fields))
    verb = action or f"update_{noun}"
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": verb,
            "pk": key,
            "preview": payload,
            "mapped_fields": updates,
            "current": existing.get(noun) or existing.get("row"),
            "details": (
                "Preview only — only these user-specified fields will change; "
                "all other current values stay as-is. Confirm then call with confirm_write=true."
            ),
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(page, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        saga_session.clear_capture()
        client = saga_grid.SagaGrid.for_operation(spec.operation)
        current = existing.get(noun) or existing.get("row") or {}
        merged: dict[str, Any] = {}
        for name, value in current.items():
            if value not in (None, ""):
                merged[str(name)] = value
        merged.update(updates)
        merged.setdefault(spec.pk, key)
        result = client.update(page, key, merged, allow_choices=True)
        payload_out = result.as_dict()
        verified = client.get(page, key)
        ok = bool(result.ok)
        return {
            "ok": ok,
            "updated": ok,
            "via": "grid",
            "screen": spec.operation,
            "pk": key,
            "changed_fields": updates,
            "endpoint": payload_out.get("endpoint"),
            "response": payload_out.get("response"),
            noun: verified,
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(
                page, f"saga-{noun}-{'updated' if ok else 'update-failed'}.png"
            ),
            "capture_path": saga_session._dump_capture(f"network-{noun}-update.json"),
            "error": None if ok else (result.message or "Update failed."),
        }

    return saga_session.run_in_session(_run)


def remove_record(
    operation: str,
    pk: str,
    *,
    noun: str,
    confirm_write: bool = False,
    action: str | None = None,
) -> dict[str, Any]:
    spec = saga_registry.get_screen(operation)
    if spec is None:
        return {"ok": False, "error": f"Unknown screen '{operation}'."}
    key = (pk or "").strip()
    if not key:
        return {"ok": False, "error": "pk cannot be empty."}
    existing = get_record(operation, key, noun=noun)
    if not existing.get("ok"):
        return existing
    verb = action or f"remove_{noun}"
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": verb,
            "pk": key,
            "preview": existing.get(noun) or existing.get("row"),
            "details": (
                f"Preview only — will delete this {spec.title} row. "
                "Confirm then call with confirm_write=true."
            ),
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        opened = saga_grid.open_screen(page, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        saga_session.clear_capture()
        client = saga_grid.SagaGrid.for_operation(spec.operation)
        result = client.delete(page, key, allow_choices=True)
        still = client.get(page, key)
        ok = bool(result.get("ok")) and still is None
        return {
            "ok": ok,
            "deleted": ok,
            "via": "grid",
            "screen": spec.operation,
            "pk": key,
            "endpoint": result.get("endpoint"),
            "response": result.get("response") or result,
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(
                page, f"saga-{noun}-{'deleted' if ok else 'delete-failed'}.png"
            ),
            "capture_path": saga_session._dump_capture(f"network-{noun}-delete.json"),
            "error": None if ok else (result.get("error") or result.get("message") or "Delete failed."),
        }

    return saga_session.run_in_session(_run)
