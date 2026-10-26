"""Reguły fonetyczne z poprawek: wykrywanie powtarzalnych zmian w szkicu (bez Qt).

Poprawka to para „słowo szkicu ASR (po regułach) → tekst po edycji
transkrybenta” razem z indeksem górnym poprawionego tekstu. Z każdej
poprawki wyodrębniamy zmianę: fragment różniący oba zapisy po odcięciu
wspólnego początku i końca (np. ``będzie → beⁿdzie`` daje ``ę → e^n``)
oraz jej miejsce w słowie (początek, koniec, środek). Gdy ta sama zmiana
powtarza się co najmniej :data:`MIN_REPEATS` razy, :func:`candidates`
zwraca propozycję reguły z gotowym wzorcem - transkrybent sprawdza ją
w edytorze reguł (podgląd i liczba dopasowań) i zapisuje.

Wzorzec jest zachowawczy: jeśli wszystkie poprawki mają ten sam znak
(albo najwyżej :data:`MAX_CONTEXT_CHARS` różnych znaków) tuż przed albo
tuż za zmianą, trafia on do wzorca jako warunek (``(?<=…)``/``(?=…)``),
jak w regułach wbudowanych (``ę(?=[dtscz])``). Samo wstawienie albo
usunięcie znaku obejmuje sąsiednią literę (zamiennik reguły nie może być
pusty). Pomijane są zmiany wielkości liter, przepisanie całego słowa
i zmiany dłuższe niż :data:`MAX_CHANGE_CHARS`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import regex

from transkryptor.i18n import tr
from transkryptor.notation.rules import (
    ANY_LANGUAGE,
    USER_PREFIX,
    PhoneticRule,
    check_rule,
)

MIN_REPEATS = 3
MAX_CHANGE_CHARS = 4
MAX_CONTEXT_CHARS = 3
LEARNED_CONFIDENCE = 0.5

INITIAL = "initial"
FINAL = "final"
INNER = "inner"


@dataclass(frozen=True)
class Correction:
    """Poprawka słowa; ``superscript`` - zakresy indeksu górnego w ``corrected``."""

    original: str
    corrected: str
    superscript: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Change:
    """Zmiana w słowie; ``after`` w składni zamiennika reguły (``^x``)."""

    before: str
    after: str
    place: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.before, self.after, self.place)


@dataclass(frozen=True)
class _Occurrence:
    change: Change
    previous: str  # znak przed zmianą ("" - początek słowa)
    following: str  # znak za zmianą ("" - koniec słowa)
    word: str


@dataclass(frozen=True)
class Candidate:
    """Propozycja reguły: zmiana, liczba poprawek, przykład i gotowa reguła."""

    change: Change
    count: int
    example: str
    rule: PhoneticRule


def _template(text: str, superscript: Iterable[int]) -> str:
    """Tekst w składni zamiennika: ``^x`` dla indeksu górnego, ``\\^``, ``\\\\``."""
    marked = set(superscript)
    parts: list[str] = []
    for index, char in enumerate(text):
        if index in marked and char not in "^\\":
            parts.append(f"^{char}")
        elif char in "^\\":
            parts.append(f"\\{char}")
        else:
            parts.append(char)
    return "".join(parts)


def _occurrence(correction: Correction) -> _Occurrence | None:
    original, corrected = correction.original, correction.corrected
    if original == corrected or original.casefold() == corrected.casefold():
        return None
    marked = {
        index for start, end in correction.superscript for index in range(start, end)
    }
    prefix = 0
    limit = min(len(original), len(corrected))
    while prefix < limit and original[prefix] == corrected[prefix]:
        # Ten sam znak, ale w poprawce w indeksie górnym, to też zmiana.
        if prefix in marked:
            break
        prefix += 1
    suffix = 0
    while (
        suffix < limit - prefix
        and original[-1 - suffix] == corrected[-1 - suffix]
        and len(corrected) - 1 - suffix not in marked
    ):
        suffix += 1
    if prefix + suffix == 0:
        return None  # przepisane całe słowo - to nie jest wzorzec zapisu
    start, end = prefix, len(original) - suffix
    new_start, new_end = prefix, len(corrected) - suffix
    if start == end or new_start == new_end:
        # Samo wstawienie albo usunięcie: wzorzec obejmuje sąsiedni znak
        # słowa - poprzedni (``e → eⁿ``, ``ie → i``), a na początku słowa
        # następny (``o → ło``).
        if start > 0:
            start -= 1
            new_start -= 1
        else:
            end += 1
            new_end += 1
    if end - start > MAX_CHANGE_CHARS or new_end - new_start > MAX_CHANGE_CHARS:
        return None
    before = original[start:end]
    after = _template(
        corrected[new_start:new_end],
        (index - new_start for index in marked if new_start <= index < new_end),
    )
    if start == 0:
        place = INITIAL
    elif end == len(original):
        place = FINAL
    else:
        place = INNER
    return _Occurrence(
        Change(before, after, place),
        original[start - 1] if start > 0 else "",
        original[end] if end < len(original) else "",
        original,
    )


def change_of(correction: Correction) -> Change | None:
    """Zmiana wyodrębniona z poprawki albo None (nie nadaje się na regułę)."""
    occurrence = _occurrence(correction)
    return None if occurrence is None else occurrence.change


def _context(chars: list[str]) -> str | None:
    """Klasa znaków kontekstu, gdy każda poprawka go ma i jest jednolity."""
    if not chars or any(not char for char in chars):
        return None
    distinct = sorted(set(chars))
    if len(distinct) > MAX_CONTEXT_CHARS:
        return None
    if len(distinct) == 1:
        return regex.escape(distinct[0])
    return "[" + "".join(regex.escape(char) for char in distinct) + "]"


def _pattern(change: Change, occurrences: list[_Occurrence]) -> str:
    pattern = regex.escape(change.before)
    if change.place == INITIAL:
        pattern = "^" + pattern
    else:
        previous = _context([o.previous for o in occurrences])
        if previous is not None:
            pattern = f"(?<={previous})" + pattern
        elif change.place != FINAL:
            # Środek słowa: zmiana nie obejmuje pierwszego znaku.
            pattern = "(?<=.)" + pattern
    if change.place == FINAL:
        pattern += "$"
    else:
        following = _context([o.following for o in occurrences])
        if following is not None:
            pattern += f"(?={following})"
    return pattern


def display_change(change: Change) -> str:
    """Zmiana do pokazania: ``ę → eⁿ`` (indeks górny jako ``^n``)."""
    return f"{change.before} → {change.after}"


def candidates(
    corrections: Iterable[Correction],
    existing: Iterable[PhoneticRule] = (),
    dismissed: Iterable[tuple[str, str, str]] = (),
    min_repeats: int = MIN_REPEATS,
) -> list[Candidate]:
    """Propozycje reguł z powtarzalnych poprawek, od najczęstszej.

    Pomija zmiany odrzucone przez użytkownika (``dismissed`` - klucze
    :attr:`Change.key`) i reguły, które już istnieją (ten sam wzorzec
    i zamiennik). Kod reguły to pierwszy wolny ``USR-n``.
    """
    groups: dict[tuple[str, str, str], list[_Occurrence]] = {}
    for correction in corrections:
        occurrence = _occurrence(correction)
        if occurrence is not None:
            groups.setdefault(occurrence.change.key, []).append(occurrence)
    rules = list(existing)
    known = {(rule.pattern, rule.replacement) for rule in rules}
    taken = {rule.code for rule in rules}
    skipped = set(dismissed)
    result: list[Candidate] = []
    for key, occurrences in sorted(groups.items(), key=lambda item: -len(item[1])):
        if len(occurrences) < min_repeats or key in skipped:
            continue
        change = occurrences[0].change
        pattern = _pattern(change, occurrences)
        if (pattern, change.after) in known:
            continue
        code = free_code(taken)
        example = occurrences[0].word
        rule = PhoneticRule(
            code=code,
            label={
                ANY_LANGUAGE: tr("learning.rule_label", change=display_change(change))
            },
            description={
                ANY_LANGUAGE: tr(
                    "learning.rule_description", count=len(occurrences), example=example
                )
            },
            pattern=pattern,
            replacement=change.after,
            confidence=LEARNED_CONFIDENCE,
            example=example,
        )
        if check_rule(rule, taken) is not None:
            continue
        taken.add(code)
        result.append(Candidate(change, len(occurrences), example, rule))
    return result


def free_code(taken: Iterable[str]) -> str:
    """Pierwszy wolny kod reguły użytkownika ``USR-n``."""
    codes = set(taken)
    number = 1
    while f"{USER_PREFIX}{number}" in codes:
        number += 1
    return f"{USER_PREFIX}{number}"
