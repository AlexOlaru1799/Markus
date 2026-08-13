from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

SS_NS = "urn:schemas-microsoft-com:office:spreadsheet"


def read_sheet_rows(path: Path) -> list[list[str]]:
    """Return all cells as strings. Supports SpreadsheetML .xls, BIFF .xls, and .xlsx."""
    data = path.read_bytes()
    if data.lstrip().startswith(b"<?xml") or b"<Workbook" in data[:800]:
        return _read_spreadsheetml(data)
    if data.startswith(b"PK"):
        return _read_xlsx(path)
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        return _read_biff(path)
    raise ValueError(f"Unsupported spreadsheet format: {path.name}")


def records_from_sheet(rows: list[list[str]]) -> list[dict[str, str]]:
    """Find the header row that contains NIR and CIF, then return dict records."""
    header_idx = 0
    for i, row in enumerate(rows[:20]):
        blob = " ".join(row).casefold()
        if "nir" in blob and "cif" in blob:
            header_idx = i
            break
    if header_idx >= len(rows):
        return []
    headers = [_norm_header(value) for value in rows[header_idx]]
    records: list[dict[str, str]] = []
    for row in rows[header_idx + 1 :]:
        if not any(str(cell).strip() for cell in row):
            continue
        rec: dict[str, str] = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            rec[header] = row[idx] if idx < len(row) else ""
        records.append(_alias_record(rec))
    return records


def _norm_header(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split()).strip()


def _alias_record(rec: dict[str, str]) -> dict[str, str]:
    aliases = {
        "nir": "NIR",
        "document furnizor": "Document furnizor",
        "number": "Document furnizor",
        "nrdoc": "Document furnizor",
        "denumire furnizor": "Denumire furnizor",
        "supplier": "Denumire furnizor",
        "cif": "CIF",
        "data doc": "Data doc",
        "date": "Data doc",
        "data scadentei": "Data scadentei",
        "data scadență": "Data scadentei",
        "due_date": "Data scadentei",
        "due date": "Data scadentei",
        "moneda": "Moneda",
        "currency": "Moneda",
        "valoare fara tva": "Valoare fara TVA",
        "valoare fără tva": "Valoare fara TVA",
        "net": "Valoare fara TVA",
        "tva": "TVA",
        "vat": "TVA",
        "valoare totala": "Valoare totala",
        "valoare totală": "Valoare totala",
        "total": "Valoare totala",
        "categorie": "Categoria",
        "category": "Categoria",
        "observatii": "Observatii",
        "status": "Status",
    }
    out: dict[str, str] = {}
    for key, value in rec.items():
        dest = aliases.get(key.casefold(), key)
        if dest not in out or not str(out[dest]).strip():
            out[dest] = value
    return out


def _read_spreadsheetml(data: bytes) -> list[list[str]]:
    root = ET.fromstring(data)
    rows: list[list[str]] = []
    for row_el in root.findall(".//{%s}Row" % SS_NS):
        cells: list[str] = []
        for cell_el in row_el.findall("{%s}Cell" % SS_NS):
            data_el = cell_el.find("{%s}Data" % SS_NS)
            cells.append("" if data_el is None or data_el.text is None else str(data_el.text))
        rows.append(cells)
    return rows


def _read_biff(path: Path) -> list[list[str]]:
    try:
        import xlrd
    except ImportError as exc:
        raise ValueError(
            "Reading SmartBill's native .xls needs the xlrd package. "
            "Reinstall Markus from source (pip install -e .) or pass a Markus-generated .xls."
        ) from exc
    book = xlrd.open_workbook(str(path), formatting_info=False)
    sheet = book.sheet_by_index(0)
    rows: list[list[str]] = []
    for ridx in range(sheet.nrows):
        row: list[str] = []
        for cidx in range(sheet.ncols):
            cell = sheet.cell(ridx, cidx)
            row.append(_biff_cell(book, cell))
        rows.append(row)
    return rows


def _biff_cell(book, cell) -> str:
    import xlrd

    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            parts = xlrd.xldate_as_tuple(cell.value, book.datemode)
            return f"{parts[2]:02d}.{parts[1]:02d}.{parts[0]:04d}"
        except Exception:
            return str(cell.value)
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        value = cell.value
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    if cell.ctype == xlrd.XL_CELL_EMPTY:
        return ""
    return str(cell.value).strip()


def _read_xlsx(path: Path) -> list[list[str]]:
    import zipfile

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", ns)))
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str]] = []
        for row_el in sheet.findall("m:sheetData/m:row", ns):
            cells: list[str] = []
            for cell_el in row_el.findall("m:c", ns):
                kind = cell_el.get("t")
                if kind == "inlineStr":
                    text = "".join(t.text or "" for t in cell_el.findall(".//m:t", ns))
                else:
                    v = cell_el.find("m:v", ns)
                    raw = "" if v is None or v.text is None else v.text
                    text = shared[int(raw)] if kind == "s" and raw.isdigit() else raw
                cells.append(text)
            rows.append(cells)
        return rows
