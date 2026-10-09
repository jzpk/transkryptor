"""Eksport dokumentu transkrypcji do DOCX.

Kontrakt ``document -> export``: wejściem jest tekst, zakresy indeksu
górnego, metadane autora i daty oraz metryczka nagrania z modelu
``Document``. Moduł nie zapisuje stanu roboczego aplikacji — jedynym
artefaktem jest plik DOCX.

Układ dokumentu (czytany z powrotem przez ``export/docx_import.py``):
tabela metryczki (dwie kolumny: etykieta, wartość; tylko niepuste pola),
akapit „Autor: … Data: …” i jeden akapit tekstu.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from docx import Document as DocxDocument

from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    PLACE,
    SIGNATURE,
    MetadataField,
    export_items,
)
from transkryptor.document.model import Document, clip_ranges
from transkryptor.errors import ExportError
from transkryptor.i18n import tr

METADATA_TABLE_STYLE = "Table Grid"


def export_docx(
    document: Document,
    path: str | Path,
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
) -> None:
    """Zapisuje dokument do pliku DOCX.

    Tekst jest zapisywany jako jeden akapit z runami; znaki objęte
    ``superscript_ranges`` otrzymują formatowanie indeksu górnego.
    Autor i data trafiają zarówno do właściwości dokumentu, jak i do
    akapitu nagłówkowego. Metryczka (pola ``fields`` w ich kolejności) trafia
    do tabeli na początku; ``core_properties.title`` to sygnatura,
    a ``keywords`` — miejscowość. ``anonymize`` pomija pola osobowe
    (także we właściwościach). Błędy zapisu są zgłaszane jako ``ExportError``.
    """
    target = Path(path)
    try:
        _write(document, target, tuple(fields), anonymize)
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


def _write(
    document: Document,
    target: Path,
    fields: tuple[MetadataField, ...],
    anonymize: bool,
) -> None:
    docx = DocxDocument()
    items = export_items(document.metadata, fields, anonymize)
    values = {field.key: value for field, value in items}

    docx.core_properties.author = document.author
    docx.core_properties.title = values.get(SIGNATURE, tr("docx.default_title"))
    docx.core_properties.keywords = values.get(PLACE, "")

    if items:
        table = docx.add_table(rows=0, cols=2)
        table.style = METADATA_TABLE_STYLE
        for field, value in items:
            label_cell, value_cell = table.add_row().cells
            label_cell.text = field.display_label
            value_cell.text = value

    if document.author or document.date:
        docx.add_paragraph(
            f"{tr('docx.author')}: {document.author}    "
            f"{tr('docx.date')}: {document.date}"
        )

    paragraph = docx.add_paragraph()
    for start, end, is_superscript in _split_runs(document):
        run = paragraph.add_run(document.text[start:end])
        if is_superscript:
            run.font.superscript = True

    docx.save(str(target))


def _split_runs(document: Document) -> list[tuple[int, int, bool]]:
    """Dzieli tekst na spójne runy (start, end, indeks_górny).

    Jedno przejście po posortowanych, scalonych zakresach — koszt liniowy
    także dla tysięcy krótkich zakresów indeksu górnego.
    """
    text_length = len(document.text)
    runs: list[tuple[int, int, bool]] = []
    position = 0
    for start, end in clip_ranges(document.superscript_ranges, text_length):
        if position < start:
            runs.append((position, start, False))
        runs.append((start, end, True))
        position = end
    if position < text_length:
        runs.append((position, text_length, False))
    return runs
