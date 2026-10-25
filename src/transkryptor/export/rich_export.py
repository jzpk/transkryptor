"""Eksport do ODT i PDF przez Qt (bez dodatkowych zależności).

Oba formaty powstają z jednego ``QTextDocument`` o układzie jak DOCX:
tabela metryczki, akapit „Autor: … Data: …” i akapity tekstu z pogrubioną
etykietą mówcy oraz indeksem górnym. ODT zapisuje ``QTextDocumentWriter``
(format ODF, indeks górny jako ``style:text-position``), PDF - ``QPdfWriter``
(A4, czcionka osadzona). Wymaga działającej ``QGuiApplication``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import (
    QFont,
    QPageLayout,
    QPageSize,
    QPdfWriter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentWriter,
    QTextFrameFormat,
    QTextLength,
    QTextTableFormat,
)

from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport

FONT_SIZE_PT = 12
PAGE_MARGIN_MM = 20
CREATOR = "Transkryptor"


def build_text_document(
    document: ExportDocument, font_family: str = ""
) -> QTextDocument:
    qdoc = QTextDocument()
    font = QFont(font_family) if font_family else QFont()
    font.setPointSize(FONT_SIZE_PT)
    qdoc.setDefaultFont(font)
    qdoc.setMetaInformation(QTextDocument.MetaInformation.DocumentTitle, document.title)
    cursor = QTextCursor(qdoc)
    plain = QTextCharFormat()
    bold = QTextCharFormat()
    bold.setFontWeight(QFont.Weight.Bold)
    superscript = QTextCharFormat()
    superscript.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)

    first = True

    def new_block() -> None:
        nonlocal first
        if not first:
            cursor.insertBlock()
        first = False

    rows = document.header_rows()
    if rows:
        table_format = QTextTableFormat()
        table_format.setBorder(0.5)
        table_format.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        table_format.setCellPadding(4)
        table_format.setCellSpacing(0)
        table_format.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        table = cursor.insertTable(len(rows), 2, table_format)
        for row, (label, value) in enumerate(rows):
            table.cellAt(row, 0).firstCursorPosition().insertText(label, plain)
            table.cellAt(row, 1).firstCursorPosition().insertText(value, plain)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        first = False
    if document.author_line:
        new_block()
        cursor.insertText(document.author_line, plain)
    for paragraph in document.paragraphs:
        new_block()
        if paragraph.speaker is not None:
            cursor.insertText(f"{paragraph.speaker.key}:", bold)
            cursor.insertText("\t", plain)
        for run in paragraph.runs:
            cursor.insertText(run.text, superscript if run.superscript else plain)
    return qdoc


def _check_writable(path: Path) -> None:
    """Zgłasza ``OSError`` przed zapisem Qt, który błędy tylko sygnalizuje."""
    with open(path, "wb"):
        pass


def write_odt(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    _check_writable(path)
    writer = QTextDocumentWriter(str(path), b"ODF")
    if not writer.write(build_text_document(document, options.font_family)):
        device = writer.device()
        raise OSError(device.errorString() if device is not None else str(path))


def write_pdf(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    _check_writable(path)
    writer = QPdfWriter(str(path))
    writer.setTitle(document.title)
    writer.setCreator(CREATOR)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM),
            QPageLayout.Unit.Millimeter,
        )
    )
    build_text_document(document, options.font_family).print_(writer)
