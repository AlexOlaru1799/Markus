"""Parse a SAGA Facturi XML into raw invoices and catalog-mapped sales documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga.documents import types as doc_types
from markus_mcp.tools.saga.documents import xml as saga_xml

DEFAULT_CONT = "704"


def parse_facturi_xml(path: str | Path, *, operation: str = "iesiri") -> dict[str, Any]:
    source = Path(path)
    tree = ET.parse(source)
    root = tree.getroot()
    kind = saga_xml.root_kind(root)

    invoices: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    line_count = 0
    total_amount = 0.0
    detail_op = "iesiri_detalii" if operation == "iesiri" else f"{operation}_detalii"

    for factura in saga_xml.findall(root, "Factura"):
        antet = saga_xml.find(factura, "Antet")
        if antet is None:
            antet = factura
        xml_lines = saga_xml.findall(factura, "Linie")
        lines: list[dict[str, str]] = []
        amount = 0.0
        for line in xml_lines:
            valoare = saga_xml.child_text(line, "Valoare")
            tva = saga_xml.child_text(line, "TVA") or "0"
            pret = saga_xml.child_text(line, "Pret") or valoare
            qty = saga_xml.child_text(line, "Cantitate") or "1"
            lines.append(
                {
                    "descriere": saga_xml.child_text(line, "Descriere"),
                    "cantitate": qty,
                    "pret": pret,
                    "valoare": valoare or pret,
                    "tva": tva,
                    "tva_proc": saga_xml.child_text(line, "TVAProc")
                    or saga_xml.child_text(line, "TVA_ART")
                    or "0",
                    "cont": saga_xml.child_text(line, "Cont")
                    or (DEFAULT_CONT if operation == "iesiri" else ""),
                    "cod": saga_xml.child_text(line, "Cod"),
                }
            )
            amount += saga_xml.number(valoare or pret) + saga_xml.number(tva)
        line_count += len(lines)
        total_amount += amount
        number = saga_xml.child_text(antet, "FacturaNumar")
        invoice = {
            "number": number,
            "date": saga_xml.child_text(antet, "FacturaData"),
            "scadent": saga_xml.child_text(antet, "FacturaScadenta")
            or saga_xml.child_text(antet, "FacturaData"),
            "client": saga_xml.child_text(antet, "ClientNume"),
            "cif": saga_xml.child_text(antet, "ClientCIF"),
            "cod": saga_xml.child_text(antet, "ClientCod"),
            "currency": saga_xml.child_text(antet, "FacturaMoneda") or "RON",
            "supplier": saga_xml.child_text(antet, "FurnizorNume"),
            "supplier_cif": saga_xml.child_text(antet, "FurnizorCIF"),
            "amount": round(amount, 2),
            "lines": lines,
        }
        invoices.append(invoice)
        documents.append(_to_document(invoice, operation=operation, detail_op=detail_op, source=str(source)))

    return {
        "kind": kind,
        "invoices": invoices,
        "documents": documents,
        "line_count": line_count,
        "total_amount": round(total_amount, 2),
        "path": str(source),
    }


def _to_document(
    invoice: dict[str, Any],
    *,
    operation: str,
    detail_op: str,
    source: str,
) -> dict[str, Any]:
    header_raw = {
        "NrDoc": invoice.get("number"),
        "Data": invoice.get("date"),
        "Scadent": invoice.get("scadent"),
        "Cod": invoice.get("cod"),
        "Valuta": invoice.get("currency"),
        "FacturaNumar": invoice.get("number"),
        "FacturaData": invoice.get("date"),
        "FacturaScadenta": invoice.get("scadent"),
        "FacturaMoneda": invoice.get("currency"),
    }
    if operation.startswith("intrari"):
        header_raw["Furnizor"] = invoice.get("supplier")
        header_raw["FurnizorNume"] = invoice.get("supplier")
        header_raw["FurnizorCod"] = invoice.get("cod")
        header_raw["FurnizorCIF"] = invoice.get("supplier_cif")
    else:
        header_raw["Client"] = invoice.get("client")
        header_raw["ClientNume"] = invoice.get("client")
        header_raw["ClientCod"] = invoice.get("cod")
    header_mapped = saga_schema.map_fields(operation, header_raw)
    mapped_lines: list[dict[str, str]] = []
    unknown: list[str] = list(header_mapped.unknown)
    for index, line in enumerate(invoice.get("lines") or []):
        line_raw = {
            "Denumire": line.get("descriere"),
            "Descriere": line.get("descriere"),
            "Cantitate": line.get("cantitate"),
            "Pret": line.get("pret"),
            "Valoare": line.get("valoare"),
            "TVA": line.get("tva"),
            "TVAProc": line.get("tva_proc"),
            "Cont": line.get("cont"),
            "Cod": line.get("cod"),
        }
        line_mapped = saga_schema.map_fields(detail_op, line_raw)
        unknown.extend(f"line[{index}]: {name}" for name in line_mapped.unknown)
        mapped_lines.append(line_mapped.fields)
    facade = doc_types.purchase_invoice if operation.startswith("intrari") else doc_types.sales_invoice
    return facade(
        header=header_mapped.fields,
        lines=mapped_lines,
        currency=str(invoice.get("currency") or "RON"),
        meta={
            "source": "facturi_xml",
            "source_path": source,
            "unknown_fields": unknown,
            "raw_number": invoice.get("number"),
        },
    )
