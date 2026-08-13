from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.dom import minidom
from xml.etree import ElementTree as ET

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.smartbill.xls_read import read_sheet_rows, records_from_sheet


def saga_facturi_filename(cif: str, when: datetime) -> str:
    """SAGA Import date name: F_<cif>_<dd>_<mm>_<yyyy>.xml"""
    digits = _cif_digits(cif)
    if not digits:
        raise ValueError("Company CIF is missing; cannot name the SAGA XML file.")
    return f"F_{digits}_{when.strftime('%d_%m_%Y')}.xml"


def convert_xls_to_saga_xml(
    xls_path: str | Path,
    output_path: Path | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Turn a SmartBill Documente furnizori spreadsheet into SAGA Facturi XML."""
    source = Path(xls_path).expanduser()
    if not source.is_file():
        return {"ok": False, "error": f"Spreadsheet not found: {source}"}
    try:
        rows = read_sheet_rows(source)
        records = records_from_sheet(rows)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not read spreadsheet: {exc}"}
    cif = _company_cif(rows)
    when = _file_date(records, date_to)
    try:
        name = saga_facturi_filename(cif, when)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    dest = (output_path.parent if output_path else data_dir() / "smartbill") / name
    result = write_facturi_xml(records, dest, source_path=str(_host(source)))
    if result.get("ok"):
        result["filename"] = dest.name
    return result


def write_facturi_xml(
    records: list[dict[str, Any]],
    output_path: Path,
    source_path: str | None = None,
) -> dict[str, Any]:
    """
    Same rules as the Flask ``process_invoices_to_xml`` processor:
    keep rows with NIR, skip CIF starting with RO, group by invoice number.
    """
    with_nir: list[dict[str, str]] = []
    skipped_no_nir = 0
    for rec in records:
        nir = _text(rec.get("NIR"))
        if not nir or nir.casefold() == "nan":
            skipped_no_nir += 1
            continue
        with_nir.append({str(k): _text(v) for k, v in rec.items()})

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for rec in with_nir:
        grouped[_text(rec.get("Document furnizor"))].append(rec)

    skipped_ro: list[str] = []
    kept: dict[str, list[dict[str, str]]] = {}
    for invoice_no, group in grouped.items():
        cif = _clean_cif(group[0].get("CIF", ""))
        if cif.upper().startswith("RO"):
            skipped_ro.append(invoice_no)
            continue
        kept[invoice_no] = group
    grouped = kept

    if not grouped:
        if skipped_ro and not with_nir:
            error = "No valid invoices found containing a NIR value."
        elif skipped_ro:
            error = (
                "All invoices with NIR have a Romanian CIF (RO…) and were skipped. "
                "SAGA XML is only built for non-RO suppliers."
            )
        else:
            error = "No valid invoices found containing a NIR value."
        return {
            "ok": False,
            "error": error,
            "row_count": len(records),
            "skipped_no_nir": skipped_no_nir,
            "skipped_ro": len(skipped_ro),
            "skipped_ro_invoices": skipped_ro[:50],
            "source_path": source_path,
        }

    root = ET.Element("Facturi")
    total_amount = 0.0
    for invoice_num, group in grouped.items():
        first = group[0]
        cif = _clean_cif(first.get("CIF", ""))
        factura = ET.SubElement(root, "Factura")
        antet = ET.SubElement(factura, "Antet")
        _el(antet, "FurnizorNume", first.get("Denumire furnizor", ""))
        _el(antet, "FurnizorCIF", cif)
        if cif:
            _el(antet, "FurnizorTara", cif[:2].upper())
        doc_num = invoice_num.replace("Fact ", "").strip()
        _el(antet, "FacturaNumar", doc_num)
        _el(antet, "FacturaData", _saga_date(first.get("Data doc", "")))
        _el(antet, "FacturaScadenta", _saga_date(first.get("Data scadentei", "")))
        moneda = _text(first.get("Moneda", "RON")).upper() or "RON"
        _el(antet, "FacturaMoneda", moneda)
        if moneda == "RON":
            _el(antet, "Curs", "1.0000")
        detalii = ET.SubElement(factura, "Detalii")
        continut = ET.SubElement(detalii, "Continut")
        for rec in group:
            linie = ET.SubElement(continut, "Linie")
            _el(linie, "Descriere", _text(rec.get("NIR")).replace(".0", ""))
            net = _text(rec.get("Valoare fara TVA", "0")) or "0"
            vat = _text(rec.get("TVA", "0")) or "0"
            _el(linie, "Cantitate", "1")
            _el(linie, "Pret", net)
            _el(linie, "Valoare", net)
            _el(linie, "TVA", vat)
            total_amount += _number(net) + _number(vat)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    xmlstr = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="    ")
    output_path.write_text(xmlstr, encoding="utf-8")
    return {
        "ok": True,
        "path": str(_host(output_path)),
        "invoice_count": len(grouped),
        "line_count": sum(len(g) for g in grouped.values()),
        "total_amount": round(total_amount, 2),
        "row_count": len(records),
        "skipped_no_nir": skipped_no_nir,
        "skipped_ro": len(skipped_ro),
        "skipped_ro_invoices": skipped_ro[:50],
        "source_path": source_path,
        "log": (
            f"Success! Converted {len(grouped)} invoices. "
            f"Total amount processed: {total_amount:.2f} RON."
        ),
    }


def _el(parent: ET.Element, tag: str, text: str) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = text
    return child


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in {"nan", "none", "-"}:
        return ""
    return text


def _clean_cif(value: str) -> str:
    return _text(value)


def _number(value: str) -> float:
    try:
        return float(value.replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


def _saga_date(value: str) -> str:
    parsed = _parse_date(value)
    if parsed:
        return parsed.strftime("%d.%m.%Y")
    text = _text(value).replace("/", ".")
    return text.split(" ")[0] if text else ""


def _parse_date(value: str) -> datetime | None:
    text = _text(value).replace("/", ".")
    if not text:
        return None
    date_only = text.split(" ")[0]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%m.%d.%Y"):
        try:
            return datetime.strptime(date_only, fmt)
        except ValueError:
            continue
    return None


def _cif_digits(value: str) -> str:
    raw = _text(value).upper()
    if raw.startswith("RO") and len(raw) > 2 and raw[2].isdigit():
        raw = raw[2:]
    return re.sub(r"\D", "", raw)


def _company_cif(rows: list[list[str]]) -> str:
    try:
        from markus_mcp.tools.smartbill.credentials import load_credentials

        creds = load_credentials()
        if creds.cif_configured:
            return creds.cif
    except Exception:
        pass
    for row in rows[:8]:
        blob = " ".join(str(cell) for cell in row)
        match = re.search(r"CIF:\s*(RO)?\s*(\d{6,12})", blob, re.I)
        if match:
            return match.group(2)
    return ""


def _file_date(records: list[dict[str, Any]], date_to: str | None) -> datetime:
    parsed_end = _parse_date(date_to or "")
    dates = [_parse_date(str(rec.get("Data doc") or "")) for rec in records]
    dates = [d for d in dates if d is not None]
    if parsed_end:
        return parsed_end
    if dates:
        return max(dates)
    return datetime.now()


def _host(path: Path) -> Path:
    data = data_dir()
    try:
        return host_data_dir() / path.relative_to(data)
    except ValueError:
        return path
