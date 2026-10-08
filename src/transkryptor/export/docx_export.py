"""Eksport dokumentu transkrypcji do DOCX.

Kontrakt ``document -> export``: wejściem jest tekst, zakresy indeksu
górnego oraz metadane autora i daty z modelu ``Document``. Moduł nie
zapisuje stanu roboczego aplikacji — jedynym artefaktem jest plik DOCX.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from docx import Document as DocxDocument

from transkryptor.document.model import Document
from transkryptor.errors import ExportError


def export_docx(document: Document, path: str | Path) -> None:
    """Zapisuje dokument do pliku DOCX.

    Tekst jest zapisywany jako jeden akapit z runami; znaki objęte
    ``superscript_ranges`` otrzymują formatowanie indeksu górnego.
    Autor i data trafiają zarówno do właściwości dokumentu, jak i do
    akapitu nagłówkowego. Błędy zapisu są zgłaszane jako ``ExportError``.
    """
    target = Path(path)
    try:
        _write(document, target)
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


def _write(document: Document, target: Path) -> None:
    docx = DocxDocument()

    docx.core_properties.author = document.author
    docx.core_properties.title = "Transkrypcja fonetyczna"

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
