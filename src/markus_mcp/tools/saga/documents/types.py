"""Canonical document facades over schema-catalog tables."""

from __future__ import annotations

from typing import Any


def sales_invoice(
    *,
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    currency: str = "RON",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = (currency or "RON").strip().upper() or "RON"
    kind = "sales_invoice" if code in {"", "RON"} else "sales_invoice_fx"
    return {
        "kind": kind,
        "currency": code,
        "header": dict(header),
        "lines": [dict(line) for line in lines],
        "meta": dict(meta or {}),
    }


def purchase_invoice(
    *,
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    currency: str = "RON",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = (currency or "RON").strip().upper() or "RON"
    kind = "purchase_invoice" if code in {"", "RON"} else "purchase_invoice_fx"
    return {
        "kind": kind,
        "currency": code,
        "header": dict(header),
        "lines": [dict(line) for line in lines],
        "meta": dict(meta or {}),
    }


def bank_bundle(
    *,
    kind: str,
    entries: list[dict[str, Any]],
    account: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label = "bank_receipts" if kind == "Incasari" else "bank_payments" if kind == "Plati" else kind
    return {
        "kind": label,
        "account": account or "",
        "entries": [dict(item) for item in entries],
        "meta": dict(meta or {}),
    }
