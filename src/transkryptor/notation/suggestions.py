"""Regułowe kandydaty zapisu fonetycznego dla tekstu ortograficznego.

Realizuje „Reguły ASR” z ``specs/transcription-rules.md``: silnik generuje
kandydatów dla znanych zjawisk z informacją o źródle i pewności. Kandydaci
są wyłącznie propozycjami — funkcja jest czysta, nie mutuje dokumentu.
Zastosowanie wykonuje UI: automatycznie tylko dla reguł wybranych przez
użytkownika (REQ-15), pozostałe na jego żądanie (ACC-12).

Zbiór reguł jest celowo mały i konserwatywny: każda reguła jest ugruntowana
przykładem ze specyfikacji. Brak korpusu referencyjnego oznacza, że pewność
jest orientacyjna, a ekspert zawsze decyduje o zastosowaniu.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+")

# Spółgłoski wyzwalające asymilację nosowości (dentalne/przedniojęzykowe
# oraz wargowe) — ugruntowane przykładami „bendzie”, „pamientam”.
_DENTAL_AFTER_E = frozenset("dtscz")
_LABIAL = frozenset("pb")


@dataclass(frozen=True)
class Suggestion:
    """Propozycja zapisu fonetycznego dla fragmentu tekstu źródłowego.

    ``superscript_ranges`` to półotwarte zakresy względem ``replacement``,
    które po zastosowaniu powinny otrzymać format indeksu górnego
    (nosowość ``m``/``n``, labializacja ``u``). ``word`` i ``word_start``
    opisują słowo źródłowe — kontekst do prezentacji propozycji.
    """

    code: str
    start: int
    end: int
    original: str
    replacement: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    source: str = "rule"
    confidence: float = 0.0
    message: str = ""
    word: str = ""
    word_start: int = 0


@dataclass(frozen=True)
class RuleInfo:
    """Opis reguły dla UI: wybór reguł stosowanych automatycznie (REQ-15)."""

    code: str
    label: str
    confidence: float


@dataclass(frozen=True)
class _Rule:
    code: str
    label: str
    message: str
    confidence: float
    transform: Callable[[str], list[_Edit]]


@dataclass(frozen=True)
class _Edit:
    """Pojedyncza zamiana w obrębie słowa (pozycje względem początku słowa)."""

    start: int
    end: int
    replacement: str
    superscript_ranges: tuple[tuple[int, int], ...] = field(default_factory=tuple)


def propose(text: str) -> list[Suggestion]:
    """Zwraca regułowych kandydatów zapisu fonetycznego dla tekstu.

    Wejściem jest zwykle hipoteza ortograficzna ASR. Wynik jest posortowany
    po pozycji i nigdy nie modyfikuje wejścia.
    """
    suggestions: list[Suggestion] = []
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        base = match.start()
        for rule in _RULES:
            for edit in rule.transform(word):
                suggestions.append(
                    Suggestion(
                        code=rule.code,
                        start=base + edit.start,
                        end=base + edit.end,
                        original=word[edit.start : edit.end],
                        replacement=edit.replacement,
                        superscript_ranges=edit.superscript_ranges,
                        confidence=rule.confidence,
                        message=rule.message,
                        word=word,
                        word_start=base,
                    )
                )
    return sorted(suggestions, key=lambda s: (s.start, s.code))


def without_overlaps(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Usuwa kandydatów nachodzących na siebie, zostawiając pewniejszych.

    Automatyczne stosowanie kilku zamian na tym samym fragmencie
    zniszczyłoby tekst, więc z każdej grupy kolizji zostaje jedna
    propozycja (wyższa pewność, przy remisie — wcześniejsza pozycja).
    Wynik jest posortowany po pozycji.
    """
    kept: list[Suggestion] = []
    for candidate in sorted(suggestions, key=lambda s: (-s.confidence, s.start)):
        if all(candidate.end <= s.start or s.end <= candidate.start for s in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda s: (s.start, s.code))


def _nasal_final_a(word: str) -> list[_Edit]:
    """Końcowe „ą” → „o” + indeks górny „m” (przykład: są → som)."""
    if len(word) > 1 and word.endswith("ą"):
        return [_Edit(len(word) - 1, len(word), "om", ((1, 2),))]
    return []


def _nasal_e_dental(word: str) -> list[_Edit]:
    """„ę” przed spółgłoską dentalną → „e” + indeks górny „n” (bendzie)."""
    return [
        _Edit(i, i + 1, "en", ((1, 2),))
        for i in range(len(word) - 1)
        if word[i] == "ę" and word[i + 1] in _DENTAL_AFTER_E
    ]


def _nasal_e_labial(word: str) -> list[_Edit]:
    """„ę” przed spółgłoską wargową → „e” + indeks górny „m” (asymilacja)."""
    return [
        _Edit(i, i + 1, "em", ((1, 2),))
        for i in range(len(word) - 1)
        if word[i] == "ę" and word[i + 1] in _LABIAL
    ]


def _nasal_a_labial(word: str) -> list[_Edit]:
    """„ą” przed spółgłoską wargową → „o” + indeks górny „m” (asymilacja)."""
    return [
        _Edit(i, i + 1, "om", ((1, 2),))
        for i in range(len(word) - 1)
        if word[i] == "ą" and word[i + 1] in _LABIAL
    ]


def _labial_initial_o(word: str) -> list[_Edit]:
    """Początkowe „o-” → indeks górny „u” + „o” (przykład: od → uod)."""
    if len(word) > 1 and word.startswith("o"):
        return [_Edit(0, 1, "uo", ((0, 1),))]
    return []


_RULES = (
    _Rule(
        code="SUG-NAS-A-FINAL",
        label="Nosowość: końcowe „ą” → „oᵐ” (są → soᵐ)",
        message="Nosowość: końcowe „ą” jako „oᵐ” (przykład ze specyfikacji: są → som).",
        confidence=0.5,
        transform=_nasal_final_a,
    ),
    _Rule(
        code="SUG-NAS-E-DENT",
        label="Nosowość: „ę” przed d/t/s/c/z → „eⁿ” (będzie → beⁿdzie)",
        message=(
            "Nosowość: „ę” przed spółgłoską dentalną jako „eⁿ” "
            "(przykład: będzie → bendzie)."
        ),
        confidence=0.4,
        transform=_nasal_e_dental,
    ),
    _Rule(
        code="SUG-NAS-E-LAB",
        label="Nosowość: „ę” przed p/b → „eᵐ”",
        message="Nosowość: „ę” przed p/b jako „eᵐ” (asymilacja wargowa).",
        confidence=0.4,
        transform=_nasal_e_labial,
    ),
    _Rule(
        code="SUG-NAS-A-LAB",
        label="Nosowość: „ą” przed p/b → „oᵐ”",
        message="Nosowość: „ą” przed p/b jako „oᵐ” (asymilacja wargowa).",
        confidence=0.4,
        transform=_nasal_a_labial,
    ),
    _Rule(
        code="SUG-LAB-U-INIT",
        label="Labializacja: początkowe „o-” → „ᵘo” (od → ᵘod)",
        message="Labializacja: początkowe „o-” jako „uo” (przykład: od → uod).",
        confidence=0.3,
        transform=_labial_initial_o,
    ),
)

RULES: tuple[RuleInfo, ...] = tuple(
    RuleInfo(rule.code, rule.label, rule.confidence) for rule in _RULES
)

__all__ = ["RULES", "RuleInfo", "Suggestion", "propose", "without_overlaps"]
