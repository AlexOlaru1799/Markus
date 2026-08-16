"""Load committed SAGA table catalogs and map user keys onto column names."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


def _schemas_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled = meipass / "markus_mcp" / "tools" / "saga" / "schemas"
        if bundled.is_dir():
            return bundled
        beside = Path(sys.executable).resolve().parent / "markus_mcp" / "tools" / "saga" / "schemas"
        if beside.is_dir():
            return beside
    return Path(__file__).resolve().parent / "schemas"


def normalize_key(value: str) -> str:
    return " ".join((value or "").strip().split()).casefold()


@dataclass
class Mapped:
    fields: dict[str, str] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)
    auto_filled: dict[str, str] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    operation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "unknown": self.unknown,
            "auto_filled": self.auto_filled,
            "missing_required": self.missing_required,
            "operation": self.operation,
        }


def _load_json(name: str) -> dict[str, Any]:
    path = _schemas_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"SAGA schema catalog not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def aliases_catalog() -> dict[str, Any]:
    return _load_json("aliases.json")


@lru_cache(maxsize=128)
def catalog_for(operation: str) -> dict[str, Any]:
    op = (operation or "").strip()
    if not op:
        raise ValueError("operation is required")
    if op.startswith("report:"):
        report_id = op.split(":", 1)[1].strip()
        entry = reports_catalog().get(report_id)
        if not isinstance(entry, dict):
            raise FileNotFoundError(f"SAGA report catalog not found: {report_id}")
        data = dict(entry)
        data.setdefault("operation", report_id)
        data.setdefault("columns", [])
        return data
    filename = f"{op}.json"
    data = _load_json(filename)
    data.setdefault("operation", op)
    data.setdefault("columns", [])
    return data


@lru_cache(maxsize=1)
def reports_catalog() -> dict[str, Any]:
    data = _load_json("reports.json")
    return data if isinstance(data, dict) else {}


def clear_catalog_cache() -> None:
    catalog_for.cache_clear()
    aliases_catalog.cache_clear()
    reports_catalog.cache_clear()


def column_map(operation: str) -> dict[str, dict[str, Any]]:
    catalog = catalog_for(operation)
    out: dict[str, dict[str, Any]] = {}
    for column in catalog.get("columns") or []:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip()
        if name:
            out[name] = column
    return out


def _alias_index(operation: str) -> dict[str, str]:
    catalog = catalog_for(operation)
    table = str(catalog.get("table") or operation)
    index: dict[str, str] = {}
    for column in catalog.get("columns") or []:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or "").strip()
        if not name:
            continue
        index[normalize_key(name)] = name
        index[normalize_key(name).replace(" ", "_")] = name
        for alias in column.get("aliases") or ():
            index[normalize_key(str(alias))] = name
            index[normalize_key(str(alias)).replace(" ", "_")] = name
    shared = (aliases_catalog().get("shared") or {}) if isinstance(aliases_catalog(), dict) else {}
    by_op = (aliases_catalog().get("by_operation") or {}) if isinstance(aliases_catalog(), dict) else {}
    extra = dict(shared)
    if isinstance(by_op, dict):
        extra.update(by_op.get(operation) or {})
        extra.update(by_op.get(table) or {})
    for alias, target in extra.items():
        target_name = str(target)
        if target_name not in column_map(operation):
            # Shared aliases may target another table; skip for this operation.
            continue
        index[normalize_key(str(alias))] = target_name
        index[normalize_key(str(alias)).replace(" ", "_")] = target_name
    return index


def map_fields(
    operation: str,
    user_payload: dict[str, Any] | None,
    *,
    apply_defaults: bool = False,
    required_on_create: bool = False,
) -> Mapped:
    """Map user keys to catalog column names. Unknown keys are reported, never invented."""
    index = _alias_index(operation)
    columns = column_map(operation)
    mapped = Mapped(operation=operation)
    for key, value in (user_payload or {}).items():
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        norm = normalize_key(str(key))
        name = index.get(norm) or index.get(norm.replace(" ", "_"))
        if not name and str(key) in columns:
            name = str(key)
        if not name:
            mapped.unknown.append(str(key))
            continue
        mapped.fields[name] = text

    if apply_defaults:
        for name, column in columns.items():
            if name in mapped.fields:
                continue
            default = column.get("defaultValue")
            if default is None or str(default).strip() == "":
                continue
            mapped.fields[name] = str(default).strip()
            mapped.auto_filled[name] = str(default).strip()

    for name, column in columns.items():
        required = bool(column.get("required"))
        if required_on_create:
            required = required or bool(column.get("required_on_create"))
        if required and name not in mapped.fields:
            mapped.missing_required.append(name)
    return mapped


def exposed_columns(operation: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for column in catalog_for(operation).get("columns") or []:
        if not isinstance(column, dict):
            continue
        if column.get("expose") is False:
            continue
        item = {
            "name": column.get("name"),
            "aliases": list(column.get("aliases") or ()),
            "kind": column.get("kind") or column.get("inputType") or "text",
            "description": column.get("description") or "",
            "required": bool(column.get("required")),
            "required_on_create": bool(column.get("required_on_create")),
        }
        select_model = str(column.get("selectModel") or column.get("select_model") or "").strip()
        if select_model:
            item["select_model"] = select_model
        fields.append(item)
    return fields


def describe_screen(operation: str) -> dict[str, Any]:
    from markus_mcp.tools.saga import lookups as saga_lookups
    from markus_mcp.tools.saga import registry as saga_registry

    spec = saga_registry.get_screen(operation)
    if spec is None:
        return {"ok": False, "error": f"Unknown screen '{operation}'.", "screens": saga_registry.list_operation_ids()}
    catalog = catalog_for(spec.schema_id)
    app_base = "https://web2.sagasoft.ro/sagac"
    try:
        from markus_mcp.tools.saga import session as saga_session

        app_base = getattr(saga_session, "DEFAULT_APP_BASE_URL", app_base)
    except Exception:
        pass
    payload: dict[str, Any] = {
        "ok": True,
        "screen": spec.operation,
        "title": spec.title,
        "table": spec.table,
        "route": spec.route,
        "url": f"{app_base}/{spec.route}",
        "primary_key": spec.pk,
        "write_style": spec.write_style,
        "risk": spec.risk,
        "named_tools": list(spec.named_tools),
        "fields": exposed_columns(spec.schema_id),
        "usage": catalog.get("usage") or spec.usage,
        "notes": list(catalog.get("notes") or spec.notes),
        "details": (
            "Pass only the fields the user specifies. Unspecified fields are left unchanged "
            "(update) or blank (create). Use either the SAGA name or an alias as the dict key."
        ),
    }
    if spec.detail_operation:
        detail_catalog = catalog_for(spec.detail_operation)
        payload["header_fields"] = payload["fields"]
        payload["line_fields"] = exposed_columns(spec.detail_operation)
        payload["detail_table"] = detail_catalog.get("table") or spec.detail_operation
        payload["usage"] = catalog.get("usage") or {
            "header": spec.usage,
            "lines": (detail_catalog.get("usage") or ""),
        }
    payload["lookups"] = saga_lookups.lookups_for_screen(spec.operation)
    if spec.detail_operation:
        payload["line_lookups"] = saga_lookups.lookups_for_screen(spec.detail_operation)
    if spec.operation == "clienti":
        payload["count"] = len(payload["fields"])
    if spec.operation == "iesiri_valuta":
        payload["usage"] = catalog.get("usage") or payload.get("usage")
    return payload


def field_catalog(operation: str) -> dict[str, dict[str, Any]]:
    """Legacy-shaped {SAGA_NAME: {aliases, kind, description, required}} dict."""
    out: dict[str, dict[str, Any]] = {}
    for column in catalog_for(operation).get("columns") or []:
        if not isinstance(column, dict) or column.get("expose") is False:
            continue
        name = str(column.get("name") or "").strip()
        if not name:
            continue
        entry = {
            "aliases": tuple(column.get("aliases") or ()),
            "kind": column.get("kind") or "text",
            "description": column.get("description") or "",
            "required": bool(column.get("required")),
            "required_on_create": bool(column.get("required_on_create")),
        }
        select_model = str(column.get("selectModel") or "").strip()
        if select_model:
            entry["select_model"] = select_model
        out[name] = entry
    return out
