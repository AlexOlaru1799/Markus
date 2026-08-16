"""Bank/cash named writes. Bank posting still uses Import extrase, not grid.create on Solduri."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import nomenclator as saga_nomenclator
from markus_mcp.tools.saga.documents.emit_incasari_xml import emit_incasari_xml
from markus_mcp.tools.saga.documents.types import bank_bundle


def _currency_of(payload: dict[str, Any] | None) -> str:
    lowered = {str(key).casefold(): value for key, value in (payload or {}).items()}
    for key in ("valuta", "currency", "moneda"):
        raw = lowered.get(key)
        if raw not in (None, ""):
            return str(raw).strip().upper() or "RON"
    return "RON"


def _entries_currency(entries: list[Any]) -> str:
    for entry in entries:
        if isinstance(entry, dict):
            currency = _currency_of(entry)
            if currency not in {"", "RON"}:
                return currency
    return "RON"


def post_bank_entries(
    document: dict[str, Any] | None = None,
    *,
    entries: list[dict[str, Any]] | None = None,
    kind: str = "bank_receipts",
    account: str = "",
    partner: str = "",
    asociere: bool = True,
    confirm_write: bool = False,
) -> dict[str, Any]:
    """Accept a BankBundle (or entries list) and post via Jurnal de Bancă Import extrase."""
    from markus_mcp.tools.saga import jurnal_banca_import as saga_bank

    payload = dict(document or {})
    if entries and not payload.get("entries"):
        payload = bank_bundle(kind=kind, entries=list(entries), account=account or None)
    if not payload.get("entries"):
        return {"ok": False, "error": "document.entries (or entries=) cannot be empty."}
    currency = _entries_currency(list(payload.get("entries") or []))
    screen = "jurnal_banca" if currency in {"", "RON"} else "jurnal_banca_valuta"
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    source = str(meta.get("source_path") or "").strip()
    if not source:
        source = str(emit_incasari_xml(payload))
        meta = dict(meta)
        meta["source_path"] = source
        meta.setdefault("source", "chat")
        payload["meta"] = meta
    treasury = account or str(payload.get("account") or "")
    result = saga_bank.import_incasari_xml(
        source,
        confirm_write=confirm_write,
        partner=partner,
        account=treasury,
        asociere=asociere,
    )
    if result.get("requires_confirmation"):
        result["action"] = "post_bank_entries"
        result["document_kind"] = payload.get("kind")
        result["entry_count"] = len(payload.get("entries") or [])
        result["currency"] = currency
        result["screen"] = screen
        result["details"] = (
            str(result.get("details") or "")
            + " Same Import extrase workflow"
            + (" with valuta account/Moneda." if screen.endswith("valuta") else ".")
        ).strip()
    else:
        result["currency"] = currency
        result["screen"] = screen
    return result


def add_casa_entry(
    fields: dict[str, Any],
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    currency = _currency_of(fields)
    operation = "registru_casa" if currency in {"", "RON"} else "registru_casa_valuta"
    result = saga_nomenclator.create_record(
        operation,
        fields,
        noun="casa_entry",
        confirm_write=confirm_write,
        action="add_casa_entry",
    )
    if result.get("requires_confirmation"):
        result["currency"] = currency
        result["screen"] = operation
        mapped = result.get("mapped_fields") or {}
        auto_filled = dict(result.get("auto_filled") or {})
        if operation == "registru_casa_valuta" and not mapped.get("Curs"):
            auto_filled["Curs"] = "(GetLastValuta on confirm if omitted)"
            result["auto_filled"] = auto_filled
            result["details"] = (
                str(result.get("details") or "")
                + " FX cash: Curs from GetLastValuta when omitted."
            ).strip()
    else:
        result["currency"] = currency
        result["screen"] = operation
    return result
