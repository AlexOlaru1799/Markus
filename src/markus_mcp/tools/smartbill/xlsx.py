from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


def write_xls(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    """Excel 2003 SpreadsheetML. Excel opens a .xls file written this way."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def cell(value: object) -> str:
        text = "" if value is None else str(value)
        return f'<Cell><Data ss:Type="String">{escape(text)}</Data></Cell>'

    body = ["<Row>" + "".join(cell(value) for value in row) + "</Row>" for row in (headers, *rows)]
    xml = (
        '<?xml version="1.0"?>\n'
        '<?mso-application progid="Excel.Sheet"?>\n'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Documente furnizori"><Table>'
        + "".join(body)
        + "</Table></Worksheet></Workbook>\n"
    )
    path.write_text(xml, encoding="utf-8")


def write_xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    """Write a minimal xlsx (no openpyxl). Excel opens this as a normal workbook."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet = _sheet_xml(headers, rows)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Documente furnizori" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def _sheet_xml(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
    ]
    for ridx, row in enumerate([headers, *rows], start=1):
        cells = []
        for cidx, value in enumerate(row):
            ref = f"{_col(cidx)}{ridx}"
            text = "" if value is None else str(value)
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'
            )
        lines.append(f'<row r="{ridx}">{"".join(cells)}</row>')
    lines.append("</sheetData></worksheet>")
    return "".join(lines)


def _col(index: int) -> str:
    n = index + 1
    letters = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))
