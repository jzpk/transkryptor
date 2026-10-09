"""Import DOCX do dokumentu transkrypcji („najlepszy wysiłek”, bez Qt).

Odczytuje runy python-docx i buduje tekst z zakresami indeksu górnego.
Dokument aplikacji jest jednoakapitowy, więc akapity są łączone znakiem
nowej linii, a raport mówi, ile ich złączono. Metadane pochodzą z tabeli
metryczki (rozpoznawanej po etykietach pól), akapitu „Autor: … Data: …”
z eksportu aplikacji oraz — gdy tych brak — z ``core_properties``.

Wszystko, czego dokument aplikacji nie wyraża (formatowanie inne niż indeks
górny, tabele poza metryczką, obrazy, przypisy), jest pomijane i liczone
w raporcie.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from transkryptor.document.metadata import DEFAULT_FIELDS, PLACE, MetadataField
from transkryptor.errors import ImportDocxError

_HEADER_RE = re.compile(r"^\s*Autor:\s*(?P<author>.*?)\s*Data:\s*(?P<date>.*?)\s*$")


@dataclass(frozen=True)
class ImportReport:
    """Co pominięto przy imporcie (liczniki wystąpień)."""

    merged_paragraphs: int = 0
    formatted_runs: dict[str, int] = field(default_factory=dict)
    skipped_tables: int = 0
    images: int = 0
    footnotes: int = 0
    unknown_metadata: tuple[str, ...] = ()

    @property
    def is_lossless(self) -> bool:
        return not self.lines()

    def lines(self) -> list[str]:
        """Pozycje raportu dla użytkownika (pusta lista = nic nie pominięto)."""
        lines: list[str] = []
        if self.merged_paragraphs:
            lines.append(
                f"Złączono {self.merged_paragraphs} {_paragraphs(self.merged_paragraphs)} "
                "w jeden tekst "
                "(granice akapitów zachowano jako nowe linie)."
            )
        if self.formatted_runs:
            kinds = ", ".join(
                f"{name} ({count})" for name, count in self.formatted_runs.items()
            )
            lines.append(f"Pominięto formatowanie inne niż indeks górny: {kinds}.")
        if self.skipped_tables:
            lines.append(f"Pominięto tabele poza metryczką: {self.skipped_tables}.")
        if self.images:
            lines.append(f"Pominięto obrazy: {self.images}.")
        if self.footnotes:
            lines.append(f"Pominięto przypisy: {self.footnotes}.")
        if self.unknown_metadata:
            lines.append(
                "Pominięto nieznane pola metryczki: "
                + ", ".join(self.unknown_metadata)
                + "."
            )
        return lines


@dataclass(frozen=True)
class ImportedDocument:
    text: str
    superscript_ranges: list[tuple[int, int]]
    author: str
    date: str
    metadata: dict[str, str]
    report: ImportReport


def import_docx(
    path: str | Path, fields: Iterable[MetadataField] = DEFAULT_FIELDS
) -> ImportedDocument:
    """Wczytuje DOCX; nieczytelny plik → ``ImportDocxError``."""
    source = Path(path)
    try:
        docx = DocxDocument(str(source))
    except Exception as exc:  # python-docx zgłasza różne wyjątki dla złego pliku
        raise ImportDocxError(
            user_message=f"Nie udało się odczytać pliku „{source.name}” jako DOCX.",
            retry_hint="Sprawdź, czy plik nie jest uszkodzony i ma format .docx "
            "(nie .doc).",
        ) from exc
    return _Reader(docx, fields).read()


class _Reader:
    def __init__(self, docx, fields: Iterable[MetadataField]) -> None:
        self._docx = docx
        labels: dict[str, str] = {}
        for metadata_field in (*DEFAULT_FIELDS, *fields):
            labels[_label_key(metadata_field.label)] = metadata_field.key
        self._labels = labels
        self._formatted: dict[str, int] = {}

    def read(self) -> ImportedDocument:
        metadata: dict[str, str] = {}
        unknown: list[str] = []
        author: str | None = None
        date = ""
        skipped_tables = 0
        paragraphs: list[Paragraph] = []
        for block in self._docx.iter_inner_content():
            in_header = not any(p.text.strip() for p in paragraphs)
            if isinstance(block, Table):
                if in_header and self._read_metadata(block, metadata, unknown):
                    continue
                skipped_tables += 1
                continue
            if in_header:
                match = _HEADER_RE.match(block.text)
                if match and author is None:
                    author, date = match["author"], match["date"]
                    continue
            paragraphs.append(block)

        while paragraphs and not paragraphs[0].text.strip():
            paragraphs.pop(0)
        while paragraphs and not paragraphs[-1].text.strip():
            paragraphs.pop()

        text_parts: list[str] = []
        ranges: list[tuple[int, int]] = []
        offset = 0
        for index, paragraph in enumerate(paragraphs):
            if index:
                text_parts.append("\n")
                offset += 1
            for run in _runs(paragraph):
                run_text = run.text
                if not run_text:
                    continue
                if _is_superscript(run):
                    ranges.append((offset, offset + len(run_text)))
                self._count_formatting(run)
                text_parts.append(run_text)
                offset += len(run_text)

        core = self._docx.core_properties
        if author is None:
            author = core.author or ""
        if PLACE not in metadata and core.keywords:
            metadata[PLACE] = core.keywords

        body = self._docx.element.body
        return ImportedDocument(
            text="".join(text_parts),
            superscript_ranges=_merge(ranges),
            author=author,
            date=date,
            metadata=metadata,
            report=ImportReport(
                merged_paragraphs=len(paragraphs) if len(paragraphs) > 1 else 0,
                formatted_runs=dict(self._formatted),
                skipped_tables=skipped_tables,
                images=len(body.xpath(".//w:drawing | .//w:pict")),
                footnotes=len(
                    body.xpath(".//w:footnoteReference | .//w:endnoteReference")
                ),
                unknown_metadata=tuple(unknown),
            ),
        )

    def _read_metadata(
        self, table: Table, metadata: dict[str, str], unknown: list[str]
    ) -> bool:
        """Tabela metryczki: dwie kolumny, co najmniej jedna znana etykieta."""
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows or any(len(cells) != 2 for cells in rows):
            return False
        if not any(_label_key(label) in self._labels for label, _value in rows):
            return False
        for label, value in rows:
            key = self._labels.get(_label_key(label))
            if key is None:
                if label or value:
                    unknown.append(label or value)
            elif value:
                metadata[key] = value
        return True

    def _count_formatting(self, run: Run) -> None:
        font = run.font
        for name, present in (
            ("pogrubienie", font.bold),
            ("kursywa", font.italic),
            ("podkreślenie", font.underline),
            ("przekreślenie", font.strike),
            ("indeks dolny", font.subscript),
        ):
            if present:
                self._formatted[name] = self._formatted.get(name, 0) + 1


def _runs(paragraph: Paragraph) -> list[Run]:
    """Runy akapitu, także te wewnątrz hiperłączy."""
    runs: list[Run] = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, Hyperlink):
            runs.extend(item.runs)
        else:
            runs.append(item)
    return runs


def _is_superscript(run: Run) -> bool:
    if run.font.superscript is not None:
        return bool(run.font.superscript)
    style = run.style
    while style is not None:
        if style.font.superscript is not None:
            return bool(style.font.superscript)
        style = style.base_style
    return False


def _paragraphs(count: int) -> str:
    """Odmiana „akapit” po liczebniku większym od 1 (2 akapity, 5 akapitów)."""
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "akapity"
    return "akapitów"


def _label_key(label: str) -> str:
    return label.strip().rstrip(":").strip().casefold()


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
