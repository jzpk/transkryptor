"""Wnioski z poprawek całego korpusu (zgłoszenie #74, bez Qt).

Różnice szkicu i tekstu każdego projektu (``draft_insights.extract_edits``)
sumują się: wzorzec, który w pojedynczym wywiadzie powtórzył się za mało
razy, żeby dać propozycję, w korpusie może się już nazbierać
(``CorpusRule.corpus_only``). Przy każdej propozycji, wymianie słowa i wstawce
jest liczba projektów, w których wystąpiła - wzorzec jednego informatora
różni się od cechy gwary całego zespołu nagrań.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from transkryptor.notation.draft_insights import (
    WORD_MIN_REPEATS,
    Edits,
    Phrase,
    Punctuation,
    Repeated,
    change_key,
    repeated,
)
from transkryptor.notation.learning import MIN_REPEATS, Candidate, candidates
from transkryptor.notation.rules import DismissedKey, PhoneticRule

CORPUS_MIN_REPEATS = 5
CORPUS_MIN_PROJECTS = 2


@dataclass(frozen=True)
class ProjectEdits:
    """Różnice jednego projektu korpusu (``estimated`` - szkic odtworzony
    z wyniku ASR, bo projekt nie ma zapisanego szkicu po wstawieniu)."""

    name: str
    edits: Edits
    estimated: bool = False


@dataclass(frozen=True)
class CorpusRule:
    """Propozycja reguły z liczbą projektów; ``corpus_only`` - w żadnym
    projekcie nie powtórzyła się dość razy, by ją tam zaproponować."""

    candidate: Candidate
    projects: int
    corpus_only: bool
    dismissed: bool


@dataclass(frozen=True)
class CorpusInsights:
    """Wnioski z projektów korpusu, które mają szkic ASR."""

    projects: int
    estimated: int
    draft_words: int
    corrected_words: int
    rules: tuple[CorpusRule, ...] = ()
    words: tuple[Repeated, ...] = ()
    added: tuple[Repeated, ...] = ()
    punctuation: Punctuation = Punctuation()
    added_count: int = 0


def _with_projects(
    found: Iterable[Repeated], per_project: Sequence[Iterable[Phrase]]
) -> tuple[Repeated, ...]:
    keys = [
        {(p.original.casefold(), p.corrected.casefold()) for p in phrases}
        for phrases in per_project
    ]
    return tuple(
        replace(
            item,
            projects=sum(
                1
                for project in keys
                if (item.original.casefold(), item.corrected.casefold()) in project
            ),
        )
        for item in found
    )


def corpus_insights(
    projects: Sequence[ProjectEdits],
    rules: Sequence[PhoneticRule],
    dismissed: Iterable[DismissedKey] = (),
    min_repeats: int = CORPUS_MIN_REPEATS,
    min_projects: int = CORPUS_MIN_PROJECTS,
) -> CorpusInsights:
    """Wnioski z różnic wszystkich projektów (od najczęstszych)."""
    skipped = frozenset(dismissed)
    corrections = [item for p in projects for item in p.edits.corrections]
    per_project = [
        Counter(change_key(item) for item in p.edits.corrections) for p in projects
    ]
    found: list[CorpusRule] = []
    for candidate in candidates(
        (item.correction for item in corrections), rules, (), min_repeats
    ):
        key = candidate.change.key
        counts = [counter[key] for counter in per_project if counter[key]]
        if len(counts) < min_projects:
            continue
        found.append(
            CorpusRule(
                candidate, len(counts), max(counts) < MIN_REPEATS, key in skipped
            )
        )
    words = [p.edits.phrases for p in projects]
    added = [p.edits.added for p in projects]
    punctuation = Punctuation()
    for project in projects:
        punctuation += project.edits.punctuation
    return CorpusInsights(
        len(projects),
        sum(1 for p in projects if p.estimated),
        sum(p.edits.draft_words for p in projects),
        sum(p.edits.corrected_words for p in projects),
        tuple(found),
        _with_projects(
            repeated((ph for phrases in words for ph in phrases), WORD_MIN_REPEATS),
            words,
        ),
        _with_projects(
            repeated((ph for phrases in added for ph in phrases), WORD_MIN_REPEATS),
            added,
        ),
        punctuation,
        sum(len(phrases) for phrases in added),
    )


__all__ = [
    "CORPUS_MIN_PROJECTS",
    "CORPUS_MIN_REPEATS",
    "CorpusInsights",
    "CorpusRule",
    "ProjectEdits",
    "corpus_insights",
]
