"""Emit a SAGA Încasări/Plăți XML from a canonical bank bundle (no Playwright)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from markus_mcp.paths import data_dir
from markus_mcp.tools.saga import schema as saga_schema


def emit_incasari_xml(document: dict[str, Any], *, dest: Path | None = None) -> Path:
    kind = str(document.get("kind") or "bank_receipts")
    root_name = "Plati" if kind in {"bank_payments", "Plati", "plati"} else "Incasari"
    root = Element(root_name)
    entries = document.get("entries") or []
    default_account = str(document.get("account") or "")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mapped = saga_schema.map_fields("jurnal_banca", entry)
        fx = saga_schema.map_fields("jurnal_banca_valuta", entry)
        row = dict(mapped.fields)
        if fx.fields.get("Valuta") and not row.get("Moneda"):
            row["Moneda"] = fx.fields["Valuta"]
        if fx.fields.get("Moneda") and not row.get("Moneda"):
            row["Moneda"] = fx.fields["Moneda"]
        linie = SubElement(root, "Linie")
        _child(linie, "Data", row.get("Data") or entry.get("data") or entry.get("date"))
        _child(linie, "Numar", row.get("NrDoc") or entry.get("numar") or entry.get("NrDoc"))
        _child(linie, "Suma", row.get("Suma") or entry.get("suma") or entry.get("amount"))
        _child(linie, "Cont", row.get("Cont") or entry.get("cont") or default_account)
        _child(linie, "Explicatie", row.get("Explicatie") or entry.get("explicatie"))
        _child(linie, "FacturaNumar", row.get("FacturaNumar") or entry.get("factura_numar"))
        _child(linie, "Moneda", row.get("Moneda") or entry.get("moneda") or entry.get("valuta") or "RON")
        if fx.fields.get("SumaValuta") or entry.get("SumaValuta"):
            _child(linie, "SumaValuta", fx.fields.get("SumaValuta") or entry.get("SumaValuta"))
        if fx.fields.get("Curs") or entry.get("Curs"):
            _child(linie, "Curs", fx.fields.get("Curs") or entry.get("Curs"))
    if dest is None:
        folder = data_dir() / "saga"
        folder.mkdir(parents=True, exist_ok=True)
        prefix = "P" if root_name == "Plati" else "I"
        stamp = datetime.now().strftime("%d_%m_%Y_%H%M%S")
        dest = folder / f"{prefix}_{stamp}.xml"
    dest.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8"))
    return dest


def _child(parent: Element, tag: str, value: Any) -> None:
    node = SubElement(parent, tag)
    node.text = "" if value is None else str(value).strip()
