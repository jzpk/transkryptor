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
from itertools import pairwise
from pathlib import Path

from docx import Document as DocxDocument

from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    PLACE,
    SIGNATURE,
    MetadataField,
    export_items,
)
from transkryptor.document.model import Document
from transkryptor.errors import ExportError

DEFAULT_TITLE = "Transkrypcja fonetyczna"
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
            user_message=f"Nie udało się zapisać pliku „{target.name}”: {exc.strerror or exc}.",
            retry_hint="Sprawdź uprawnienia katalogu i spróbuj ponownie.",
        ) from exc
    except Exception as exc:
        raise ExportError(
            user_message=f"Nie udało się wyeksportować dokumentu: {exc}.",
            retry_hint="Spróbuj ponownie lub wybierz inną lokalizację.",
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
    docx.core_properties.title = values.get(SIGNATURE, DEFAULT_TITLE)
    docx.core_properties.keywords = values.get(PLACE, "")

    if items:
        table = docx.add_table(rows=0, cols=2)
        table.style = METADATA_TABLE_STYLE
        for field, value in items:
            label_cell, value_cell = table.add_row().cells
            label_cell.text = field.label
            value_cell.text = value

    if document.author or document.date:
        docx.add_paragraph(f"Autor: {document.author}    Data: {document.date}")

    paragraph = docx.add_paragraph()
    for start, end, is_superscript in _split_runs(document):
        run = paragraph.add_run(document.text[start:end])
        if is_superscript:
            run.font.superscript = True

    docx.save(str(target))


def _split_runs(document: Document) -> list[tuple[int, int, bool]]:
    """Dzieli tekst na spójne runy (start, end, indeks_górny)."""
    text_length = len(document.text)
    if text_length == 0:
        return []
    boundaries = {0, text_length}
    for start, end in document.superscript_ranges:
        boundaries.add(max(0, start))
        boundaries.add(min(text_length, end))
    ordered = sorted(boundaries)
    runs: list[tuple[int, int, bool]] = []
    for left, right in pairwise(ordered):
        if left >= right:
            continue
        is_superscript = any(
            start <= left and right <= end for start, end in document.superscript_ranges
        )
        runs.append((left, right, is_superscript))
    return runs
