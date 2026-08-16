"""Parse a SAGA Încasări / Plăți XML into raw lines and a catalog-mapped bank bundle."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga.documents import types as doc_types
from markus_mcp.tools.saga.documents import xml as saga_xml


def parse_incasari_xml(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    tree = ET.parse(source)
    root = tree.getroot()
    kind = saga_xml.root_kind(root)
    lines_out: list[dict[str, Any]] = []
    mapped_entries: list[dict[str, str]] = []
    unknown: list[str] = []
    lines_by_key: dict[str, dict[str, Any]] = {}
    dates: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    currencies: Counter[str] = Counter()
    total = 0.0
    xml_lines = saga_xml.findall(root, "Linie")
    for node in xml_lines:
        row = {
            "data": saga_xml.child_text(node, "Data"),
            "numar": saga_xml.child_text(node, "Numar"),
            "suma": round(saga_xml.number(saga_xml.child_text(node, "Suma")), 2),
            "cont": saga_xml.child_text(node, "Cont"),
            "explicatie": saga_xml.child_text(node, "Explicatie"),
            "factura_numar": saga_xml.child_text(node, "FacturaNumar"),
            "moneda": saga_xml.child_text(node, "Moneda") or "RON",
        }
        dates[row["data"]] += 1
        if row["cont"]:
            accounts[row["cont"]] += 1
        currencies[row["moneda"]] += 1
        total += float(row["suma"] or 0)
        key = "|".join((row["data"], row["numar"], f"{row['suma']:.2f}"))
        lines_by_key[key] = row
        lines_out.append(row)
        mapped = saga_schema.map_fields(
            "jurnal_banca",
            {
                "Data": row["data"],
                "Numar": row["numar"],
                "Suma": row["suma"],
                "Cont": row["cont"],
                "Explicatie": row["explicatie"],
                "FacturaNumar": row["factura_numar"],
                "Moneda": row["moneda"],
            },
        )
        unknown.extend(mapped.unknown)
        mapped_entries.append(mapped.fields)

    default_account = accounts.most_common(1)[0][0] if accounts else ""
    document = doc_types.bank_bundle(
        kind=kind,
        entries=mapped_entries,
        account=default_account,
        meta={
            "source": "incasari_xml",
            "source_path": str(source),
            "unknown_fields": unknown,
        },
    )
    return {
        "kind": kind,
        "line_count": len(xml_lines),
        "total_amount": round(total, 2),
        "dates": [{"date": key, "count": count} for key, count in dates.most_common()],
        "accounts": [{"account": key, "count": count} for key, count in accounts.most_common()],
        "currencies": [{"currency": key, "count": count} for key, count in currencies.most_common()],
        "default_account": default_account,
        "lines": lines_out,
        "lines_by_key": lines_by_key,
        "document": document,
        "path": str(source),
    }
