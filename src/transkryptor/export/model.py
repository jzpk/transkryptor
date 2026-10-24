"""Wspólny model wyjścia eksporterów (bez Qt).

``ExportDocument`` to dokument przygotowany do zapisu w dowolnym formacie:
metryczka po anonimizacji i w kolejności konfiguracji, mówcy (etykiety
informatorów puste przy anonimizacji), akapity z mówcą i runami indeksu
górnego, kotwice czasowe i ścieżka nagrania dla formatów z czasami oraz
komentarze recenzji (eksportuje je tylko DOCX; anonimizacja je pomija).
Eksportery (``export/registry.py``) czytają tylko ten model — nie
``Document`` ani ustawienia.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from transkryptor.document.anchors import Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    PLACE,
    SIGNATURE,
    MetadataField,
    export_items,
)
from transkryptor.document.model import Document, clip_ranges
from transkryptor.document.speakers import Speaker, legend, paragraph_spans
from transkryptor.i18n import tr


@dataclass(frozen=True)
class ExportRun:
    text: str
    superscript: bool = False


@dataclass(frozen=True)
class ExportParagraph:
    """Akapit ``text[start:end]`` z mówcą i runami."""

    start: int
    end: int
    runs: tuple[ExportRun, ...]
    speaker: Speaker | None = None

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass(frozen=True)
class ExportDocument:
    text: str
    paragraphs: tuple[ExportParagraph, ...]
    author: str = ""
    date: str = ""
    metadata: tuple[tuple[MetadataField, str], ...] = ()
    speakers: tuple[Speaker, ...] = ()
    uses_speakers: bool = False
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    anchors: tuple[Anchor, ...] = ()
    audio_path: Path | None = None
    anonymize: bool = False
    comments: tuple[Comment, ...] = ()
    # Konfiguracja pól zespołu (placeholdery szablonu DOCX dla pól bez wartości).
    fields: tuple[MetadataField, ...] = DEFAULT_FIELDS

    def value(self, key: str) -> str:
        """Wartość pola metryczki po anonimizacji (pusta, gdy brak)."""
        return next((value for field, value in self.metadata if field.key == key), "")

    @property
    def title(self) -> str:
        return self.value(SIGNATURE) or tr("docx.default_title")

    @property
    def keywords(self) -> str:
        return self.value(PLACE)

    @property
    def speaker_legend(self) -> str:
        """Legenda mówców do metryczki; pusta, gdy dokument nie używa mówców."""
        return legend(self.speakers) if self.uses_speakers else ""

    def header_rows(self) -> list[tuple[str, str]]:
        """Wiersze metryczki (etykieta, wartość) z legendą mówców na końcu."""
        rows = [(field.display_label, value) for field, value in self.metadata]
        if self.speaker_legend:
            rows.append((tr("docx.speakers"), self.speaker_legend))
        return rows

    @property
    def author_line(self) -> str:
        """Akapit „Autor: … Data: …” (pusty bez autora i daty)."""
        if not (self.author or self.date):
            return ""
        return (
            f"{tr('docx.author')}: {self.author}    " f"{tr('docx.date')}: {self.date}"
        )


def build_export_document(
    document: Document,
    fields: Iterable[MetadataField] = DEFAULT_FIELDS,
    anonymize: bool = False,
    anchors: Iterable[Anchor] = (),
    audio_path: str | Path | None = None,
    comments: Iterable[Comment] = (),
) -> ExportDocument:
    """Model wyjścia z dokumentu; ``anonymize`` pomija dane osobowe.

    Przy anonimizacji pomijane są też komentarze — ich autorzy i treść mogą
    zawierać dane osobowe.
    """
    fields = tuple(fields)
    speakers = tuple(
        replace(speaker, label="") if anonymize and speaker.is_informant else speaker
        for speaker in document.speakers
    )
    by_key = {speaker.key: speaker for speaker in speakers}
    runs = split_runs(document.text, document.superscript_ranges)
    paragraphs = tuple(
        ExportParagraph(
            start,
            end,
            slice_runs(document.text, runs, start, end),
            by_key.get(document.paragraph_speakers.get(index, "")),
        )
        for index, (start, end) in enumerate(paragraph_spans(document.text))
    )
    return ExportDocument(
        text=document.text,
        paragraphs=paragraphs,
        author=document.author,
        date=document.date,
        metadata=tuple(export_items(document.metadata, fields, anonymize)),
        speakers=speakers,
        uses_speakers=bool(document.paragraph_speakers),
        superscript_ranges=tuple(document.superscript_ranges),
        anchors=tuple(anchors),
        audio_path=Path(audio_path) if audio_path is not None else None,
        anonymize=anonymize,
        comments=() if anonymize else tuple(comments),
        fields=tuple(fields),
    )


def split_runs(
    text: str, superscript_ranges: Iterable[tuple[int, int]]
) -> list[tuple[int, int, bool]]:
    """Dzieli tekst na spójne runy (start, end, indeks_górny).

    Jedno przejście po posortowanych, scalonych zakresach — koszt liniowy
    także dla tysięcy krótkich zakresów indeksu górnego.
    """
    text_length = len(text)
    runs: list[tuple[int, int, bool]] = []
    position = 0
    for start, end in clip_ranges(list(superscript_ranges), text_length):
        if position < start:
            runs.append((position, start, False))
        runs.append((start, end, True))
        position = end
    if position < text_length:
        runs.append((position, text_length, False))
    return runs


def slice_runs(
    text: str, runs: list[tuple[int, int, bool]], start: int, end: int
) -> tuple[ExportRun, ...]:
    """Runy akapitu ``[start, end)`` (bez przejścia po całym tekście)."""
    result: list[ExportRun] = []
    index = max(bisect_right(runs, (start, len(text) + 1, True)) - 1, 0)
    while index < len(runs):
        run_start, run_end, superscript = runs[index]
        if run_start >= end:
            break
        piece_start, piece_end = max(run_start, start), min(run_end, end)
        if piece_start < piece_end:
            result.append(ExportRun(text[piece_start:piece_end], superscript))
        index += 1
    return tuple(result)
