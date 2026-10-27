"""Raport gotowości do oddania: co zostało do zrobienia przed eksportem (bez Qt).

Zbiera w jednym miejscu informacje rozproszone po panelach okna:
niezamknięte (niezignorowane) ostrzeżenia walidatora, niesprawdzone
niepewne słowa szkicu ASR, otwarte komentarze, akapity bez mówcy (gdy
dokument w ogóle przypisuje mówców) i puste pola metryczki. Pozycja raportu
ma kategorię, opis i zakres w tekście (pozycje Pythona) albo klucz pola
metryczki - okno raportu (``ui/readiness_dialog.py``) przechodzi z niej do
miejsca w tekście lub do pola formularza.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from transkryptor.document.comments import Comment
from transkryptor.document.metadata import MetadataField, enabled_fields
from transkryptor.document.speakers import paragraph_spans
from transkryptor.notation.validator import NotationWarning

WARNINGS = "warnings"
UNCERTAIN = "uncertain"
COMMENTS = "comments"
SPEAKERS = "speakers"
METADATA = "metadata"
CATEGORIES = (WARNINGS, UNCERTAIN, COMMENTS, SPEAKERS, METADATA)


@dataclass(frozen=True)
class Issue:
    """Pozycja raportu; ``field`` - klucz pola metryczki (kategoria METADATA)."""

    category: str
    label: str
    start: int = 0
    end: int = 0
    field: str = ""


@dataclass(frozen=True)
class ReadinessReport:
    issues: tuple[Issue, ...] = ()

    @property
    def is_ready(self) -> bool:
        return not self.issues

    def of(self, category: str) -> list[Issue]:
        return [issue for issue in self.issues if issue.category == category]


def build_report(
    text: str,
    warnings: Iterable[NotationWarning] = (),
    uncertain: Iterable[tuple[int, int]] = (),
    comments: Iterable[Comment] = (),
    paragraph_speakers: Mapping[int, str] | None = None,
    metadata: Mapping[str, str] | None = None,
    fields: Iterable[MetadataField] = (),
) -> ReadinessReport:
    """Raport z bieżącego stanu dokumentu, w kolejności kategorii i tekstu.

    ``uncertain`` to zakresy niepoprawionych niepewnych słów, a ``comments``
    - komentarze z bieżącymi zakresami (rozwiązane są pomijane). Akapity bez
    mówcy są zgłaszane tylko wtedy, gdy któryś akapit ma mówcę: dokument
    bez podziału na mówców jest poprawny.
    """
    issues: list[Issue] = []
    issues.extend(
        Issue(WARNINGS, f"{w.code}: {w.message}", w.start, w.end)
        for w in sorted(warnings, key=lambda w: (w.start, w.end))
    )
    issues.extend(
        Issue(UNCERTAIN, text[start:end], start, end)
        for start, end in sorted(uncertain)
    )
    issues.extend(
        Issue(COMMENTS, comment.text, comment.start, comment.end)
        for comment in sorted(comments, key=lambda c: (c.start, c.end))
        if not comment.resolved
    )
    if paragraph_speakers:
        issues.extend(
            Issue(SPEAKERS, text[start:end], start, end)
            for index, (start, end) in enumerate(paragraph_spans(text))
            if index not in paragraph_speakers and text[start:end].strip()
        )
    values = metadata or {}
    issues.extend(
        Issue(METADATA, field.display_label, field=field.key)
        for field in enabled_fields(fields)
        if not values.get(field.key, "").strip()
    )
    return ReadinessReport(tuple(issues))
