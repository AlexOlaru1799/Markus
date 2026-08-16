"""Format-agnostic sales/purchase documents: saga_add_iesire / saga_add_intrare."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga import session as saga_session
from markus_mcp.tools.saga.documents import types as doc_types
from markus_mcp.tools.saga.documents.validate import validate


def _clean_map(payload: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if value is None or str(value).strip() == "":
            continue
        out[str(key)] = value
    return out


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _num(value: Any, default: str = "0.00") -> str:
    parsed = _as_float(value)
    if parsed is None:
        return default
    return f"{parsed:.2f}"


def _currency_of(header: dict[str, Any], document: dict[str, Any] | None = None) -> str:
    lowered = {str(key).casefold(): value for key, value in header.items()}
    raw = ""
    for key in ("valuta", "currency", "facturamoneda", "factura_moneda", "moneda"):
        if lowered.get(key) not in (None, ""):
            raw = lowered[key]
            break
    if not raw:
        raw = (document or {}).get("currency") or ""
    return str(raw).strip().upper() or "RON"


def _split_document(
    header: dict[str, Any] | None,
    lines: list[dict[str, Any]] | None,
    document: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if isinstance(document, dict) and (document.get("header") or document.get("lines")):
        header_in = dict(document.get("header") or {})
        lines_in = list(document.get("lines") or [])
        meta = dict(document.get("meta") or {})
        if header:
            header_in.update(_clean_map(header))
        if lines:
            lines_in = list(lines)
        return _clean_map(header_in), [_clean_map(line) for line in lines_in if isinstance(line, dict)], meta
    return _clean_map(header), [_clean_map(line) for line in (lines or []) if isinstance(line, dict)], {}


def _map_document(operation: str, header: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    spec = saga_registry.require_screen(operation)
    mapped_header = saga_schema.map_fields(operation, header)
    mapped_lines: list[dict[str, str]] = []
    unknown: list[str] = list(mapped_header.unknown)
    missing: list[str] = []
    detail = spec.detail_operation or f"{operation}_detalii"
    for index, line in enumerate(lines):
        line_mapped = saga_schema.map_fields(detail, line, required_on_create=True)
        unknown.extend(f"line[{index}]: {name}" for name in line_mapped.unknown)
        if line_mapped.missing_required:
            missing.append(f"line[{index}]: {', '.join(line_mapped.missing_required)}")
        if not line_mapped.fields:
            missing.append(f"line[{index}] has no recognizable fields")
        mapped_lines.append(line_mapped.fields)
    partner_key = "Furnizor" if operation.startswith("intrari") else "Client"
    if partner_key not in mapped_header.fields and "Cod" not in mapped_header.fields:
        missing.append(f"{partner_key} or Cod")
    if "Data" not in mapped_header.fields:
        missing.append("Data")
    if operation.endswith("valuta") and "Valuta" not in mapped_header.fields:
        missing.append("Valuta")
    return {
        "header": mapped_header.fields,
        "lines": mapped_lines,
        "unknown": unknown,
        "missing": missing,
        "detail": detail,
        "pk": spec.pk,
    }


def _prepare_ron_line(line: dict[str, str]) -> dict[str, str]:
    out = dict(line)
    qty = _as_float(out.get("Cantitate"), 1.0) or 1.0
    pret = _as_float(out.get("PretUnitar") or out.get("Valoare"), 0.0) or 0.0
    valoare = _as_float(out.get("Valoare"))
    if valoare is None:
        valoare = qty * pret
    tva_rate = _as_float(out.get("TVA_ART"), 0.0) or 0.0
    tva = _as_float(out.get("TVA"))
    if tva is None:
        tva = valoare * tva_rate / 100.0
    out.setdefault("Cantitate", _num(qty, "1"))
    out.setdefault("PretUnitar", _num(pret))
    out["Valoare"] = _num(valoare)
    out["TVA"] = _num(tva)
    out["Total"] = _num(valoare + tva)
    if out.get("Denumire") and not out.get("DenumireArticolServiciu"):
        out["DenumireArticolServiciu"] = out["Denumire"]
    return out


def _prepare_fx_line(line: dict[str, str], *, curs: str) -> dict[str, str]:
    from markus_mcp.tools.saga import iesiri_valuta as fx

    return fx._prepare_line_amounts(line, curs=curs)


def _header_defaults(header: dict[str, str], *, fx: bool) -> dict[str, str]:
    out = dict(header)
    out.setdefault("TVAI", "0")
    out.setdefault("Validat", "0")
    out.setdefault("Tip", "")
    zeros = ["Valoare", "TVA", "Total", "Neachitat", "Adaos"]
    if fx:
        zeros.extend(["ValoareValuta", "TVAValuta", "TotalValuta", "NeachitatValuta"])
    for key in zeros:
        out.setdefault(key, "0.00")
    if not out.get("Scadent") and out.get("Data"):
        out["Scadent"] = out["Data"]
    return out


def field_catalog(operation: str) -> dict[str, Any]:
    return saga_schema.describe_screen(operation)


def post_on_page(page, operation: str, header: dict[str, str], lines: list[dict[str, str]]) -> dict[str, Any]:
    from markus_mcp.tools.saga import ensure as saga_ensure

    spec = saga_registry.require_screen(operation)
    purchase = operation.startswith("intrari")
    resolved = saga_ensure.resolve_on_page(page, dict(header), purchase=purchase)
    if not resolved.get("ok"):
        return resolved
    opened = saga_grid.open_screen(page, spec.route)
    if not opened.get("ok"):
        return {"ok": False, **opened}
    fx = operation.endswith("valuta")
    header_data = dict(resolved["header"])
    auto_filled: dict[str, str] = {}
    if fx:
        from markus_mcp.tools.saga import iesiri_valuta as fx_mod

        if not header_data.get("Tip"):
            tip = fx_mod._fetch_tip_factura(page, header_data.get("Data") or "")
            if tip:
                header_data["Tip"] = tip
                auto_filled["Tip"] = tip
        if header_data.get("Valuta") and header_data.get("Data") and not header_data.get("Curs"):
            curs = fx_mod._fetch_fx_rate(page, valuta=header_data["Valuta"], data=header_data["Data"])
            if curs:
                header_data["Curs"] = curs
                auto_filled["Curs"] = curs
    header_data = _header_defaults(header_data, fx=fx)
    client = saga_grid.SagaGrid.for_operation(operation)
    if not header_data.get("NrDoc"):
        generated = client.next_index(
            page,
            params={
                "data": header_data.get("Data") or "",
                "Data": header_data.get("Data") or "",
                "tip": header_data.get("Tip") or "",
                "Tip": header_data.get("Tip") or "",
            },
        )
        if generated:
            header_data["NrDoc"] = generated
            auto_filled["NrDoc"] = generated
    prepared_lines = [
        _prepare_fx_line(line, curs=header_data.get("Curs") or "0") if fx else _prepare_ron_line(line)
        for line in lines
    ]
    header_result = client.create(page, header_data, allow_choices=True)
    pk = spec.pk
    new_id = header_result.new_id or saga_protocol.created_record_id(header_result.raw, header_data)
    if new_id and new_id == str(header_data.get("Cod") or "").strip():
        new_id = ""
    if header_result.ok:
        found = client.get(page, header_data.get("NrDoc") or "")
        if found:
            looked = saga_protocol.row_get(found, pk, "Id", "ID")
            if looked and looked != str(header_data.get("Cod") or "").strip():
                new_id = looked
    if not header_result.ok or not new_id:
        return {
            "ok": False,
            "error": "Header create failed.",
            "outcome": header_result.outcome,
            "message": header_result.message,
            "response": header_result.raw,
            "header": header_data,
        }
    line_results: list[dict[str, Any]] = []
    detail_op = spec.detail_operation
    for line in prepared_lines:
        linked = dict(line)
        linked[pk] = new_id
        if detail_op:
            line_result = saga_grid.SagaGrid.for_operation(detail_op).create(page, linked, allow_choices=True)
        else:
            line_result = header_result
        line_results.append(line_result.as_dict())
        if not line_result.ok:
            return {
                "ok": False,
                "error": "Line create failed.",
                "id": new_id,
                "number": header_data.get("NrDoc"),
                "response": line_result.raw,
                "line_results": line_results,
            }
    verified = client.get(page, new_id) or client.get(page, header_data.get("NrDoc") or "")
    details = client.details(page, new_id, detail_op) if detail_op else {"rows": []}
    return {
        "ok": True,
        "created": True,
        "via": "grid",
        "screen": operation,
        "id": new_id,
        "number": header_data.get("NrDoc"),
        "header": header_data,
        "line_count": len(line_results),
        "row": verified,
        "details": details.get("rows") or [],
        "header_result": header_result.as_dict(),
        "line_results": line_results,
        "auto_filled": auto_filled,
        "matched_partner": resolved.get("matched"),
    }


def _add(
    *,
    ron_operation: str,
    fx_operation: str,
    header: dict[str, Any] | None,
    lines: list[dict[str, Any]] | None,
    document: dict[str, Any] | None,
    confirm_write: bool,
    action: str,
) -> dict[str, Any]:
    raw_header, raw_lines, meta = _split_document(header, lines, document)
    if not raw_header:
        return {"ok": False, "error": "header cannot be empty.", "writable_fields": field_catalog(ron_operation)}
    if not raw_lines:
        return {"ok": False, "error": "lines cannot be empty — provide at least one line."}
    currency = _currency_of(raw_header, document)
    operation = ron_operation if currency in {"", "RON"} else fx_operation
    mapped = _map_document(operation, raw_header, raw_lines)
    if mapped["unknown"]:
        return {
            "ok": False,
            "error": f"Unknown field(s): {', '.join(mapped['unknown'])}",
            "unknown_fields": mapped["unknown"],
            "writable_fields": field_catalog(operation),
        }
    if mapped["missing"]:
        return {"ok": False, "error": "Missing required: " + "; ".join(mapped["missing"]), "mapped": mapped}
    facade = doc_types.purchase_invoice if ron_operation.startswith("intrari") else doc_types.sales_invoice
    errors = validate(
        operation,
        facade(header=mapped["header"], lines=mapped["lines"], currency=currency, meta=meta),
    )
    if errors:
        return {"ok": False, "error": "; ".join(errors), "validation": errors}
    if not confirm_write:
        from markus_mcp.tools.saga import ensure as saga_ensure

        auto_note: dict[str, str] = {}
        if not mapped["header"].get("NrDoc"):
            auto_note["NrDoc"] = "(GetNrDoc on confirm if omitted)"
        if operation.endswith("valuta") and mapped["header"].get("Valuta") and not mapped["header"].get("Curs"):
            auto_note["Curs"] = "(GetCursValutar on confirm if omitted)"
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": action,
            "screen": operation,
            "currency": currency,
            "preview": {"header": raw_header, "lines": raw_lines},
            "mapped": {"header": mapped["header"], "lines": mapped["lines"]},
            "ensure_partner": saga_ensure.preview_note(
                mapped["header"], purchase=ron_operation.startswith("intrari")
            ),
            "auto_filled": auto_note,
            "details": (
                f"Preview only — will create a {operation} document with these user-specified "
                "fields only. Missing Clienți/Furnizori abort on confirm (no auto-create). "
                "Confirm then call with confirm_write=true."
            ),
            "writable_fields": field_catalog(operation),
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        saga_session.clear_capture()
        posted = post_on_page(page, operation, mapped["header"], mapped["lines"])
        posted["url"] = page.url
        posted["screenshot_path"] = saga_session._save_screenshot(
            page, f"saga-{action.replace('_', '-')}.png"
        )
        posted["capture_path"] = saga_session._dump_capture(f"network-{action}.json")
        return posted

    return saga_session.run_in_session(_run)


def add_iesire(
    header: dict[str, Any] | None = None,
    lines: list[dict[str, Any]] | None = None,
    document: dict[str, Any] | None = None,
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return _add(
        ron_operation="iesiri",
        fx_operation="iesiri_valuta",
        header=header,
        lines=lines,
        document=document,
        confirm_write=confirm_write,
        action="add_iesire",
    )


def add_intrare(
    header: dict[str, Any] | None = None,
    lines: list[dict[str, Any]] | None = None,
    document: dict[str, Any] | None = None,
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return _add(
        ron_operation="intrari",
        fx_operation="intrari_valuta",
        header=header,
        lines=lines,
        document=document,
        confirm_write=confirm_write,
        action="add_intrare",
    )
