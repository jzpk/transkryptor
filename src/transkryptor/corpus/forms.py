"""Słownik form: unikalne formy wyrazowe projektu albo korpusu (bez Qt).

Forma to ciąg liter (z łącznikiem albo apostrofem w środku, np.
``bez-tego``) zapisany z indeksem górnym jako ``^x`` - ``be^ndzie``
i ``bendzie`` to różne formy, bo różnią się zapisem realizacji. Bez
rozróżniania wielkości liter formy są zapisane małymi literami.

Dla każdej formy słownik zbiera wszystkie wystąpienia (projekt i zakres
tekstu), z których okno buduje konkordancję i odsłuch. :func:`similar_forms`
wskazuje formy różniące się jednym znakiem (``jag``/``jak``, ``be^ndzie``/
``bendzie``) - kandydatów na niespójność zapisu tej samej realizacji.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

import regex

from transkryptor.corpus.concordance import informant_ranges, superscript_mask
from transkryptor.corpus.projects import CorpusProject
from transkryptor.document.search import restrict_to

WORD_PATTERN = regex.compile(r"[\p{L}\p{M}]+(?:['’\-][\p{L}\p{M}]+)*")
# Krótsze formy nie dostają podobnych - przy 1-2 literach (``a``/``i``,
# ``to``/``ta``) jeden znak różnicy to zwykle inne słowo.
MIN_SIMILAR_LENGTH = 3


@dataclass(frozen=True)
class Occurrence:
    project: CorpusProject
    start: int
    end: int


@dataclass
class FormEntry:
    form: str
    occurrences: list[Occurrence] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def project_count(self) -> int:
        return len({id(occurrence.project) for occurrence in self.occurrences})


def word_spans(text: str) -> Iterator[tuple[int, int]]:
    """Zakresy wyrazów tekstu."""
    for match in WORD_PATTERN.finditer(text):
        yield match.span()


def form_of(
    text: str,
    superscript_ranges: Sequence[tuple[int, int]],
    start: int,
    end: int,
    case_sensitive: bool = False,
) -> str:
    """Forma wyrazu ``text[start:end]`` (indeks górny jako ``^x``)."""
    word = text[start:end]
    if not any(s < end and e > start for s, e in superscript_ranges):
        return word if case_sensitive else word.lower()
    flags = superscript_mask(len(text), superscript_ranges, start, end)
    return "".join(
        ("^" if flags[i] else "") + (char if case_sensitive else char.lower())
        for i, char in enumerate(word)
    )


def form_index(
    projects: Iterable[CorpusProject],
    case_sensitive: bool = False,
    informant_only: bool = False,
) -> list[FormEntry]:
    """Formy z wystąpieniami: od najczęstszych, przy równej liczbie - alfabetycznie."""
    entries: dict[str, FormEntry] = {}
    for project in projects:
        state = project.state
        spans = list(word_spans(state.text))
        if informant_only:
            spans = restrict_to(spans, informant_ranges(project))
        ranges = state.superscript_ranges
        for start, end in spans:
            form = form_of(state.text, ranges, start, end, case_sensitive)
            entry = entries.get(form)
            if entry is None:
                entry = entries[form] = FormEntry(form)
            entry.occurrences.append(Occurrence(project, start, end))
    return sorted(entries.values(), key=lambda e: (-e.count, sort_key(e.form)))


def sort_key(form: str) -> tuple[str, str]:
    """Klucz sortowania form: bez znaczników ``^`` i wielkości liter."""
    return (form.replace("^", "").casefold(), form)


def similar_forms(forms: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Formy różniące się od danej jednym znakiem (zamiana, dodanie, usunięcie).

    Metoda „symetrycznego usuwania”: dwie formy są podobne, gdy po usunięciu
    najwyżej jednego znaku z każdej dają ten sam ciąg - koszt liniowy
    względem łącznej długości form zamiast porównywania każdej z każdą.
    Uwzględnia też przestawienie sąsiednich znaków (``jak``/``jka``).
    """
    unique = sorted(set(forms), key=sort_key)
    by_variant: dict[str, set[str]] = defaultdict(set)
    for form in unique:
        if len(form.replace("^", "")) < MIN_SIMILAR_LENGTH:
            continue
        for variant in _deletions(form):
            by_variant[variant].add(form)
    similar: dict[str, set[str]] = defaultdict(set)
    for group in by_variant.values():
        if len(group) < 2:
            continue
        for form in group:
            similar[form].update(group - {form})
    return {
        form: tuple(sorted(similar[form], key=sort_key))
        for form in unique
        if similar.get(form)
    }


def _deletions(form: str) -> set[str]:
    return {form, *(form[:i] + form[i + 1 :] for i in range(len(form)))}
