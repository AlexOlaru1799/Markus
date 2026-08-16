"""Emit a SAGA Facturi XML from a canonical sales/purchase invoice (no Playwright)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from markus_mcp.paths import data_dir
from markus_mcp.tools.saga import schema as saga_schema


def emit_facturi_xml(document: dict[str, Any], *, dest: Path | None = None) -> Path:
    invoices = document.get("invoices") or document.get("documents") or [document]
    root = Element("Facturi")
    for item in invoices:
        if not isinstance(item, dict):
            continue
        header_in = dict(item.get("header") or item)
        lines_in = list(item.get("lines") or [])
        kind = str(item.get("kind") or document.get("kind") or "sales_invoice")
        purchase = kind.startswith("purchase")
        header_op = "intrari" if purchase else "iesiri"
        line_op = f"{header_op}_detalii"
        header = saga_schema.map_fields(header_op, header_in).fields
        factura = SubElement(root, "Factura")
        antet = SubElement(factura, "Antet")
        _child(antet, "FacturaNumar", header.get("NrDoc") or header_in.get("FacturaNumar"))
        _child(antet, "FacturaData", header.get("Data") or header_in.get("FacturaData"))
        _child(antet, "FacturaScadenta", header.get("Scadent") or header.get("Data"))
        _child(antet, "FacturaMoneda", item.get("currency") or header.get("Valuta") or "RON")
        if purchase:
            _child(antet, "FurnizorNume", header.get("Furnizor") or header_in.get("FurnizorNume"))
            _child(antet, "FurnizorCod", header.get("Cod") or header_in.get("FurnizorCod"))
        else:
            _child(antet, "ClientNume", header.get("Client") or header_in.get("ClientNume"))
            _child(antet, "ClientCod", header.get("Cod") or header_in.get("ClientCod"))
        for line in lines_in:
            if not isinstance(line, dict):
                continue
            mapped = saga_schema.map_fields(line_op, line).fields
            linie = SubElement(factura, "Linie")
            _child(linie, "Descriere", mapped.get("Denumire") or line.get("Descriere"))
            _child(linie, "Cantitate", mapped.get("Cantitate") or line.get("Cantitate") or "1")
            _child(linie, "Pret", mapped.get("PretUnitar") or mapped.get("PretUnitarValuta") or line.get("Pret"))
            _child(linie, "Valoare", mapped.get("Valoare"))
            _child(linie, "TVAProc", mapped.get("TVA_ART") or line.get("TVAProc"))
            _child(linie, "Cont", mapped.get("Cont") or line.get("Cont"))
    if dest is None:
        folder = data_dir() / "saga"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%d_%m_%Y_%H%M%S")
        dest = folder / f"F_emit_{stamp}.xml"
    dest.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8"))
    return dest


def _child(parent: Element, tag: str, value: Any) -> None:
    node = SubElement(parent, tag)
    node.text = "" if value is None else str(value).strip()
