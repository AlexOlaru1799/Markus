"""Validate a canonical document against the committed schema catalog."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import schema as saga_schema


def validate(operation: str, document: dict[str, Any], *, required_on_create: bool = True) -> list[str]:
    errors: list[str] = []
    header = document.get("header") if isinstance(document.get("header"), dict) else document
    mapped = saga_schema.map_fields(operation, header, required_on_create=required_on_create)
    errors.extend(f"unknown field: {name}" for name in mapped.unknown)
    errors.extend(f"missing required: {name}" for name in mapped.missing_required)

    spec_detail = None
    try:
        from markus_mcp.tools.saga import registry as saga_registry

        spec = saga_registry.get_screen(operation)
        spec_detail = spec.detail_operation if spec else None
    except Exception:
        spec_detail = None
    if spec_detail and isinstance(document.get("lines"), list):
        for index, line in enumerate(document.get("lines") or []):
            if not isinstance(line, dict):
                errors.append(f"line[{index}] is not an object")
                continue
            line_mapped = saga_schema.map_fields(
                spec_detail,
                line,
                required_on_create=required_on_create,
            )
            errors.extend(f"line[{index}] unknown field: {name}" for name in line_mapped.unknown)
            errors.extend(f"line[{index}] missing required: {name}" for name in line_mapped.missing_required)
    return errors
