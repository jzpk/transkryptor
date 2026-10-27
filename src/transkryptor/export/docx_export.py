"""Eksport dokumentu transkrypcji do DOCX, także na szablonie instytucji.

Kontrakt ``document -> export``: wejściem jest model wyjścia
``ExportDocument`` (``export/model.py``) - tekst z akapitami, mówcami
i indeksem górnym, autor, data i metryczka. Moduł nie zapisuje stanu
roboczego aplikacji - jedynym artefaktem jest plik DOCX.

Układ dokumentu (czytany z powrotem przez ``export/docx_import.py``):
tabela metryczki (dwie kolumny: etykieta, wartość; tylko niepuste pola,
na końcu legenda mówców), akapit „Autor: … Data: …” i akapity tekstu -
akapit z mówcą zaczyna się pogrubioną etykietą ``B:`` i tabulatorem.
Szablon (``export/docx_template.py``) może przenieść metryczkę i tekst
w wybrane miejsca oraz wypełnić placeholdery w nagłówku i stopce.
Komentarze recenzji stają się komentarzami Worda obejmującymi swój
fragment; odpowiedzi z wątku są kolejnymi akapitami komentarza (Word
nie ma wątków w podstawowym formacie komentarzy).
"""

from __future__ import annotations

import contextlib
from bisect import bisect_right
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from transkryptor.document.comments import Comment
from transkryptor.document.metadata import DEFAULT_FIELDS, MetadataField
from transkryptor.document.model import Document
from transkryptor.errors import ExportError
from transkryptor.export.docx_template import (
    AUTHOR,
    DATE,
    FIELD,
    METADATA,
    SPEAKERS,
    SPECIAL,
    TRANSCRIPT,
    empty_copy,
    find_placeholder,
    iter_paragraphs,
    open_template,
    placeholder_key,
    placeholder_names,
    remove_placeholder,
    replace_placeholders,
    uses_field_placeholders,
)
from transkryptor.export.model import ExportDocument, build_export_document
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.i18n import tr

METADATA_TABLE_STYLE = "Table Grid"


def export_docx(
    document: Document,
    path: str | Path,
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
    options: ExportOptions | None = None,
    comments: Iterable[Comment] = (),
) -> ExportReport:
    """Zapisuje dokument do pliku DOCX i zwraca raport (np. błędny szablon).

    Każdy akapit tekstu to akapit DOCX z runami; znaki objęte
    ``superscript_ranges`` otrzymują formatowanie indeksu górnego.
    Autor i data trafiają zarówno do właściwości dokumentu, jak i do
    akapitu nagłówkowego. Metryczka (pola ``fields`` w ich kolejności) trafia
    do tabeli na początku; ``core_properties.title`` to sygnatura,
    a ``keywords`` - miejscowość. ``anonymize`` pomija pola osobowe
    (także we właściwościach). Błędy zapisu są zgłaszane jako ``ExportError``.
    """
    report = ExportReport()
    write_docx(
        build_export_document(document, fields, anonymize, comments=comments),
        path,
        options,
        report,
    )
    return report


def write_docx(
    document: ExportDocument,
    path: str | Path,
    options: ExportOptions | None = None,
    report: ExportReport | None = None,
) -> None:
    """Zapisuje model wyjścia do DOCX; błędy jako ``ExportError``.

    Błędny szablon nie blokuje eksportu (ACC-56): plik powstaje na szablonie
    wbudowanym, a raport mówi dlaczego.
    """
    target = Path(path)
    try:
        _write(document, target, options or ExportOptions(), report or ExportReport())
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


def _open(options: ExportOptions, report: ExportReport) -> tuple[Any, bool]:
    """Dokument szablonu (True) albo pusty dokument wbudowany (False)."""
    if options.template_path:
        try:
            return open_template(options.template_path), True
        except ValueError as error:
            report.warn(tr("template.report.fallback", reason=error))
    docx = DocxDocument()
    if options.font_family:
        font = docx.styles["Normal"].font
        font.name = options.font_family
        fonts = docx.styles["Normal"].element.get_or_add_rPr().get_or_add_rFonts()
        for attribute in ("w:eastAsia", "w:cs"):
            fonts.set(qn(attribute), options.font_family)
    return docx, False


def _write(
    document: ExportDocument, target: Path, options: ExportOptions, report: ExportReport
) -> None:
    docx, templated = _open(options, report)
    docx.core_properties.author = document.author
    docx.core_properties.title = document.title
    docx.core_properties.keywords = document.keywords

    transcript_at: Paragraph | None = None
    metadata_at: Paragraph | None = None
    default_header = True
    if templated:
        transcript_at = find_placeholder(docx, TRANSCRIPT)
        metadata_at = find_placeholder(docx, METADATA)
        default_header = metadata_at is None and not uses_field_placeholders(
            docx, document.fields
        )
        _fill_placeholders(docx, document, report)

    if metadata_at is not None:
        _metadata_table(docx, document, before=metadata_at)
        remove_placeholder(metadata_at, METADATA)
    elif default_header:
        _metadata_table(docx, document, before=transcript_at)
        if document.author_line:
            _new_paragraph(docx, transcript_at).add_run(document.author_line)

    # Granice komentarzy dzielą runy, bo komentarz Worda obejmuje całe runy.
    boundaries = sorted(
        {position for c in document.comments for position in (c.start, c.end)}
    )
    placed: list[tuple[int, int, Run]] = []
    for paragraph in document.paragraphs:
        target_paragraph = _new_paragraph(docx, transcript_at)
        if paragraph.speaker is not None:
            target_paragraph.add_run(f"{paragraph.speaker.key}:").bold = True
            target_paragraph.add_run("\t")
        position = paragraph.start
        for run in paragraph.runs:
            for start, end in _pieces(position, position + len(run.text), boundaries):
                text = run.text[start - position : end - position]
                docx_run = target_paragraph.add_run(text)
                if run.superscript:
                    docx_run.font.superscript = True
                placed.append((start, end, docx_run))
            position += len(run.text)
    if transcript_at is not None:
        remove_placeholder(transcript_at, TRANSCRIPT)
    for comment in document.comments:
        _add_comment(docx, comment, placed)

    docx.save(str(target))


def _pieces(start: int, end: int, boundaries: list[int]) -> list[tuple[int, int]]:
    """Zakres ``[start, end)`` podzielony na granicach komentarzy."""
    cuts = boundaries[bisect_right(boundaries, start) : bisect_right(boundaries, end)]
    edges = [start, *(cut for cut in cuts if cut < end), end]
    return [(a, b) for a, b in zip(edges, edges[1:], strict=False) if a < b]


def _add_comment(
    docx: Any, comment: Comment, placed: list[tuple[int, int, Run]]
) -> None:
    """Komentarz Worda na runach fragmentu (punktowy - na sąsiednim runie)."""
    runs = [
        run for start, end, run in placed if start < comment.end and end > comment.start
    ]
    if not runs:
        after = [run for start, _end, run in placed if start >= comment.start]
        runs = after[:1] or [run for _start, _end, run in placed[-1:]]
    if not runs:
        return
    author = comment.author or tr("docx.comment.anonymous")
    word_comment = docx.add_comment(
        [runs[0], runs[-1]],
        text=comment.text,
        author=author,
        initials=_initials(author),
    )
    if comment.created:
        word_comment._comment_elm.set(qn("w:date"), f"{comment.created}:00")
    for reply in comment.replies:
        word_comment.add_paragraph(
            tr(
                "docx.comment.reply",
                author=reply.author or tr("docx.comment.anonymous"),
                date=reply.created.replace("T", " "),
                text=reply.text,
            )
        )


def _initials(author: str) -> str:
    return "".join(word[0] for word in author.split())[:4].upper()


def _new_paragraph(docx: Any, before: Paragraph | None) -> Paragraph:
    """Akapit na końcu dokumentu albo przed akapitem placeholdera (z jego stylem)."""
    if before is None:
        return docx.add_paragraph()
    element = empty_copy(before)
    before._p.addprevious(element)
    return Paragraph(element, before._parent)


def _metadata_table(
    docx: Any, document: ExportDocument, before: Paragraph | None
) -> None:
    rows = document.header_rows()
    if not rows:
        return
    table = docx.add_table(rows=0, cols=2)
    # Szablon bez stylu tabeli z siatką - zostaje styl domyślny.
    with contextlib.suppress(KeyError, ValueError):
        table.style = METADATA_TABLE_STYLE
    for label, value in rows:
        label_cell, value_cell = table.add_row().cells
        label_cell.text = label
        value_cell.text = value
    if before is not None:
        before._p.addprevious(table._tbl)


def _fill_placeholders(
    docx: Any, document: ExportDocument, report: ExportReport
) -> None:
    names = placeholder_names(document.fields)
    structural = {TRANSCRIPT, METADATA}

    def resolve(name: str) -> str | None:
        kind = names.get(placeholder_key(name))
        if kind is None:
            return None
        group, key = kind
        if group == FIELD:
            return document.value(key)
        if group == SPECIAL and key == AUTHOR:
            return document.author
        if group == SPECIAL and key == DATE:
            return document.date
        if group == SPECIAL and key == SPEAKERS:
            return document.speaker_legend
        return None

    unknown: list[str] = []
    for paragraph in iter_paragraphs(docx):
        for name in replace_placeholders(paragraph, resolve):
            kind = names.get(placeholder_key(name))
            if (kind is None or kind[1] not in structural) and name not in unknown:
                unknown.append(name)
    if unknown:
        report.warn(
            tr(
                "template.report.unknown",
                names=", ".join(f"{{{{{name}}}}}" for name in unknown),
            )
        )
