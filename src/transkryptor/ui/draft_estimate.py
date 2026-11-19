"""Szkic odniesienia odtworzony z wyniku ASR projektu (zgłoszenie #74).

Projekty sprzed 0.11 (i projekty, w których szkic wstawiono inaczej) nie mają
zapisanego szkicu po wstawieniu. Wnioski z poprawek odtwarzają go wtedy
z zapisanego wyniku ASR tą samą drogą co przy wstawianiu: układ „pytanie -
odpowiedź”, zapis szkicu, zapis wielokropka i reguły wybrane w panelu ASR -
według bieżących ustawień, więc wynik jest przybliżony (ustawienia mogły się
zmienić od transkrypcji). Mówców szkic odtworzony nie ma.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from transkryptor.asr.project_draft import result_from_draft
from transkryptor.asr.qa_layout import question_answer_layout, question_detector
from transkryptor.asr.results import draft_text
from transkryptor.document.diff import Version
from transkryptor.document.model import normalize_ranges
from transkryptor.document.project import ProjectState
from transkryptor.notation.ellipsis import EllipsisStyle, normalize_ellipses
from transkryptor.notation.rules import PhoneticRule
from transkryptor.notation.suggestions import (
    Suggestion,
    propose_with_report,
    without_overlaps,
)
from transkryptor.settings import AsrSettings
from transkryptor.ui.draft_styler import DraftStyler


@dataclass(frozen=True)
class DraftRecipe:
    """Jak wstawiany jest szkic: ustawienia, wielokropek i reguły."""

    styler: DraftStyler
    settings: AsrSettings
    ellipsis: EllipsisStyle
    rules: Sequence[PhoneticRule]
    selected: Collection[str]


def apply_suggestions(text: str, suggestions: Sequence[Suggestion]) -> Version:
    """Tekst po zamianach (rozłącznych) z indeksem górnym zamienników."""
    pieces: list[str] = []
    ranges: list[tuple[int, int]] = []
    position = length = 0
    for suggestion in sorted(suggestions, key=lambda item: item.start):
        pieces.append(text[position : suggestion.start])
        length += suggestion.start - position
        ranges.extend(
            (length + s, length + e) for s, e in suggestion.superscript_ranges
        )
        pieces.append(suggestion.replacement)
        length += len(suggestion.replacement)
        position = suggestion.end
    pieces.append(text[position:])
    return Version("".join(pieces), tuple(normalize_ranges(ranges)))


def estimated_baseline(state: ProjectState, recipe: DraftRecipe) -> Version | None:
    """Szkic po wstawieniu odtworzony z wyniku ASR (None - projekt bez szkicu)."""
    result = result_from_draft(state.asr)
    if result is None:
        return None
    if recipe.settings.qa_layout:
        result = question_answer_layout(
            result, question_detector(state.asr_context.questionnaire)
        )
    text = normalize_ellipses(draft_text(recipe.styler.apply(result)), recipe.ellipsis)
    if not text.strip():
        return None
    proposal = propose_with_report(text, recipe.rules)
    chosen = [
        suggestion
        for suggestion in without_overlaps(proposal.suggestions, recipe.selected)
        if suggestion.code in recipe.selected
    ]
    return apply_suggestions(text, chosen)


def project_baseline(
    state: ProjectState, recipe: DraftRecipe
) -> tuple[Version | None, bool]:
    """Szkic odniesienia projektu i czy jest odtworzony (przybliżony)."""
    if state.draft_baseline is not None:
        return state.draft_baseline, False
    return estimated_baseline(state, recipe), True


__all__ = ["DraftRecipe", "apply_suggestions", "estimated_baseline", "project_baseline"]
