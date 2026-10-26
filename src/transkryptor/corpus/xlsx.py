"""Minimalny zapis arkusza XLSX (Office Open XML) bez zależności (bez Qt).

Jeden arkusz z wierszem nagłówka (pogrubionym i zablokowanym przy
przewijaniu) i komórkami tekstowymi albo liczbowymi. Teksty trafiają do
komórek jako ``inlineStr`` - bez tabeli współdzielonych napisów, którą
Excel, LibreOffice i biblioteki arkuszy i tak odczytują poprawnie.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from io import BytesIO
from xml.sax.saxutils import escape

Cell = str | int | float

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# Styl 0 - zwykła komórka z zawijaniem do góry, styl 1 - nagłówek pogrubiony.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

# Arkusz Excela ma najwyżej 31 znaków nazwy i nie zna części znaków.
_SHEET_NAME_FORBIDDEN = str.maketrans({char: " " for char in "[]:*?/\\"})
MAX_CELL_TEXT = 32_767
MAX_COLUMN_WIDTH = 60


def column_name(index: int) -> str:
    """Nazwa kolumny arkusza dla indeksu od zera: 0 → A, 26 → AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def xlsx_bytes(
    header: Sequence[str], rows: Sequence[Sequence[Cell]], sheet_name: str
) -> bytes:
    """Zawartość pliku XLSX z jednym arkuszem."""
    name = sheet_name.translate(_SHEET_NAME_FORBIDDEN).strip()[:31] or "Sheet1"
    quoted = escape(name, {'"': "&quot;"})
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{quoted}" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        archive.writestr("xl/styles.xml", _STYLES)
        archive.writestr("xl/worksheets/sheet1.xml", _sheet(header, rows))
    return buffer.getvalue()


def _sheet(header: Sequence[str], rows: Sequence[Sequence[Cell]]) -> str:
    widths = [len(title) for title in header]
    lines: list[str] = []
    table: list[Sequence[Cell]] = [header, *rows]
    for row_index, row in enumerate(table, start=1):
        style = 1 if row_index == 1 else 0
        cells: list[str] = []
        for column, value in enumerate(row):
            reference = f"{column_name(column)}{row_index}"
            if column < len(widths):
                widths[column] = max(widths[column], len(str(value)))
            cells.append(_cell(reference, value, style))
        lines.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    columns = "".join(
        f'<col min="{i}" max="{i}" width="{min(width + 2, MAX_COLUMN_WIDTH)}"'
        ' customWidth="1"/>'
        for i, width in enumerate(widths, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        + (f"<cols>{columns}</cols>" if columns else "")
        + f"<sheetData>{''.join(lines)}</sheetData></worksheet>"
    )


def _cell(reference: str, value: Cell, style: int) -> str:
    style_attr = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, int | float):
        return f'<c r="{reference}"{style_attr}><v>{value}</v></c>'
    text = _xml_text(value)[:MAX_CELL_TEXT]
    return (
        f'<c r="{reference}"{style_attr} t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(text)}</t></is></c>'
    )


def _xml_text(value: str) -> str:
    """Tekst bez znaków sterujących niedozwolonych w XML 1.0."""
    return "".join(char for char in value if char in "\t\n\r" or ord(char) >= 0x20)
