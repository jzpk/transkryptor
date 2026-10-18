"""Eksport dokumentu transkrypcji do DOCX.

Kontrakt ``document -> export``: wejściem jest model wyjścia
``ExportDocument`` (``export/model.py``) — tekst z akapitami, mówcami
i indeksem górnym, autor, data i metryczka. Moduł nie zapisuje stanu
roboczego aplikacji — jedynym artefaktem jest plik DOCX.

Układ dokumentu (czytany z powrotem przez ``export/docx_import.py``):
tabela metryczki (dwie kolumny: etykieta, wartość; tylko niepuste pola,
na końcu legenda mówców), akapit „Autor: … Data: …” i akapity tekstu —
akapit z mówcą zaczyna się pogrubioną etykietą ``B:`` i tabulatorem.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from docx import Document as DocxDocument

from transkryptor.document.metadata import DEFAULT_FIELDS, MetadataField
from transkryptor.document.model import Document
from transkryptor.errors import ExportError
from transkryptor.export.model import ExportDocument, build_export_document
from transkryptor.i18n import tr

METADATA_TABLE_STYLE = "Table Grid"


def export_docx(
    document: Document,
    path: str | Path,
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
) -> None:
    """Zapisuje dokument do pliku DOCX.

    Każdy akapit tekstu to akapit DOCX z runami; znaki objęte
    ``superscript_ranges`` otrzymują formatowanie indeksu górnego.
    Autor i data trafiają zarówno do właściwości dokumentu, jak i do
    akapitu nagłówkowego. Metryczka (pola ``fields`` w ich kolejności) trafia
    do tabeli na początku; ``core_properties.title`` to sygnatura,
    a ``keywords`` — miejscowość. ``anonymize`` pomija pola osobowe
    (także we właściwościach). Błędy zapisu są zgłaszane jako ``ExportError``.
    """
    write_docx(build_export_document(document, fields, anonymize), path)


def write_docx(document: ExportDocument, path: str | Path) -> None:
    """Zapisuje model wyjścia do DOCX; błędy jako ``ExportError``."""
    target = Path(path)
    try:
        _write(document, target)
    except ExportError:
        raise
    except OSError as exc:
        raise ExportError(
            user_message=tr(
                "docx_export.error.write",
                name=target.name,
                reason=exc.strerror or exc,
            ),
            retry_hint=tr("docx_export.error.write.hint"),
        ) from exc
    except Exception as exc:
        raise ExportError(
            user_message=tr("docx_export.error.other", reason=exc),
            retry_hint=tr("docx_export.error.other.hint"),
        ) from exc


def _write(document: ExportDocument, target: Path) -> None:
    docx = DocxDocument()
    docx.core_properties.author = document.author
    docx.core_properties.title = document.title
    docx.core_properties.keywords = document.keywords

    rows = document.header_rows()
    if rows:
        table = docx.add_table(rows=0, cols=2)
        table.style = METADATA_TABLE_STYLE
        for label, value in rows:
            label_cell, value_cell = table.add_row().cells
            label_cell.text = label
            value_cell.text = value

    if document.author_line:
        docx.add_paragraph(document.author_line)

    for paragraph in document.paragraphs:
        target_paragraph = docx.add_paragraph()
        if paragraph.speaker is not None:
            target_paragraph.add_run(f"{paragraph.speaker.key}:").bold = True
            target_paragraph.add_run("\t")
        for run in paragraph.runs:
            docx_run = target_paragraph.add_run(run.text)
            if run.superscript:
                docx_run.font.superscript = True

    docx.save(str(target))
