"""Wnioski z poprawek szkicu ASR (zgłoszenie #74, bez Qt).

Szkic tuż po wstawieniu (``document/draft_baseline.py``) porównujemy
z bieżącym tekstem słowo po słowie (interpunkcja nie wiąże dopasowania -
kropka z innego wiersza nie przesuwa par słów; w zamienionym fragmencie
słowa paruje ``notation/word_alignment.py``); mówców porównujemy w akapitach,
które w obu wersjach zaczyna ta sama para słów. Różnice dzielimy na rodzaje:

- **poprawki słów** (para słów albo ten sam tekst z nowym indeksem górnym) -
  trafiają do ``notation/learning.candidates`` i dają propozycje reguł
  zapisu; słowo przepisane w całości (albo połączone, rozdzielone) to
  kandydat do słownika ASR - model zapisuje je źle zawsze tak samo;
- **wstawki** - słowa dopisane przez transkrybenta (model je pominął, np.
  „nie?”, powtórzenia) i usunięte (model je dodał);
- **interpunkcja i wielka litera** - usunięte przecinki i kropki, zdania
  zmienione na małą literę, rozwinięte skróty: podpowiedź ustawień „Zapisu
  szkicu”;
- **mówcy** - akapity ze zmienionym mówcą (ocena podziału na mówców).

:func:`extract_edits` zbiera surowe różnice jednej transkrypcji (korpus
sumuje je między projektami - ``notation/corpus_insights.py``), a
:func:`draft_insights` składa z nich wnioski dla jednego projektu.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

import regex

from transkryptor.asr.abbreviations import ABBREVIATIONS
from transkryptor.document.diff import Version
from transkryptor.document.speakers import paragraph_spans
from transkryptor.notation.learning import (
    MIN_REPEATS,
    Candidate,
    Correction,
    candidates,
    change_of,
)
from transkryptor.notation.rules import DismissedKey, PhoneticRule
from transkryptor.notation.suggestions import propose
from transkryptor.notation.word_alignment import align_words, rewritten, runs

# Słowo: litery wraz ze znakami łączącymi (diakrytyki zapisu fonetycznego).
_WORD_RE = regex.compile(r"[\p{L}\p{M}]+")
CONTEXT_CHARS = 30
# Wymiana całego słowa i wstawka liczą się od tylu powtórzeń.
WORD_MIN_REPEATS = 2
# Progi podpowiedzi ustawień zapisu szkicu.
VERBATIM_MIN_ADDED = 5
PLAIN_MIN_PUNCTUATION = 10
PLAIN_MIN_LOWERCASED = 5
ABBREVIATIONS_MIN = 2


@dataclass(frozen=True)
class Located:
    """Poprawka słowa z miejscem w bieżącym tekście (``position``)."""

    correction: Correction
    position: int


@dataclass(frozen=True)
class Phrase:
    """Słowo albo fraza ze szkicu i z bieżącego tekstu (miejsce w bieżącym)."""

    original: str
    corrected: str
    position: int


@dataclass(frozen=True)
class SpeakerEdit:
    """Akapit (w bieżącym tekście) ze zmienionym mówcą."""

    paragraph: int
    start: int
    text: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class Punctuation:
    """Interpunkcja i wielka litera: ile usunięto, zmieniono, rozwinięto."""

    commas_removed: int = 0
    periods_removed: int = 0
    others_removed: int = 0
    lowercased: int = 0
    abbreviations: int = 0

    def __add__(self, other: Punctuation) -> Punctuation:
        return Punctuation(
            self.commas_removed + other.commas_removed,
            self.periods_removed + other.periods_removed,
            self.others_removed + other.others_removed,
            self.lowercased + other.lowercased,
            self.abbreviations + other.abbreviations,
        )

    @property
    def removed(self) -> int:
        return self.commas_removed + self.periods_removed + self.others_removed


@dataclass(frozen=True)
class Edits:
    """Surowe różnice szkicu i tekstu jednej transkrypcji."""

    draft_words: int
    corrections: tuple[Located, ...] = ()
    phrases: tuple[Phrase, ...] = ()
    added: tuple[Phrase, ...] = ()
    removed: tuple[Phrase, ...] = ()
    punctuation: Punctuation = Punctuation()
    speakers: tuple[SpeakerEdit, ...] = ()

    @property
    def corrected_words(self) -> int:
        return len(self.corrections) + len(self.phrases)


# --- różnice -------------------------------------------------------------------


def _words(text: str, offset: int = 0) -> list[tuple[str, int, int]]:
    return [
        (match.group(), offset + match.start(), offset + match.end())
        for match in _WORD_RE.finditer(text)
    ]


def _superscript(version: Version, start: int, end: int) -> tuple[tuple[int, int], ...]:
    """Zakresy indeksu górnego w ``[start, end)`` względem ``start``."""
    return tuple(
        (max(s, start) - start, min(e, end) - start)
        for s, e in version.superscript_ranges
        if s < end and e > start
    )


def _mask(version: Version, start: int, end: int) -> frozenset[int]:
    return frozenset(
        index for s, e in _superscript(version, start, end) for index in range(s, e)
    )


def _punctuation_removed(before: str, after: str) -> Punctuation:
    """Przecinki, kropki (bez wielokropków) i średniki/dwukropki mniej w ``after``."""

    def dots(text: str) -> int:
        return text.replace("...", "").replace("…", "").count(".")

    others = sum(max(0, before.count(mark) - after.count(mark)) for mark in ";:")
    return Punctuation(
        max(0, before.count(",") - after.count(",")),
        max(0, dots(before) - dots(after)),
        others,
    )


# Skrót (bez kropki) → słowa rozwinięcia: „np” → („na”, „przykład”).
_EXPANSIONS = {
    short.rstrip(".").casefold(): tuple(full.casefold().split())
    for short, full in ABBREVIATIONS.items()
}


def _is_abbreviation(old: Sequence[str], new: Sequence[str]) -> bool:
    lowered_new = [word.casefold() for word in new]
    for word in old:
        full = _EXPANSIONS.get(word.casefold())
        if full and any(
            tuple(lowered_new[i : i + len(full)]) == full
            for i in range(len(lowered_new))
        ):
            return True
    return False


_Word = tuple[str, int, int]


class _Collector:
    """Rozdziela różnice słów szkicu i tekstu na rodzaje."""

    def __init__(self, baseline: Version, current: Version) -> None:
        self.baseline, self.current = baseline, current
        self.corrections: list[Located] = []
        self.phrases: list[Phrase] = []
        self.added: list[Phrase] = []
        self.removed: list[Phrase] = []
        self.punctuation = _punctuation_removed(baseline.text, current.text)
        self.speakers: list[SpeakerEdit] = []
        # Pary słów (pozycja w szkicu, pozycja w tekście) - do mówców akapitów.
        self.matched: list[tuple[int, int]] = []

    def compare(self, speakers: bool = True) -> None:
        old, new = _words(self.baseline.text), _words(self.current.text)
        matcher = SequenceMatcher(
            None, [w for w, _, _ in old], [w for w, _, _ in new], autojunk=False
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for (word, a_start, a_end), (_, b_start, b_end) in zip(
                    old[i1:i2], new[j1:j2], strict=True
                ):
                    self.matched.append((a_start, b_start))
                    if _mask(self.baseline, a_start, a_end) != _mask(
                        self.current, b_start, b_end
                    ):
                        self._word(word, word, b_start, b_end)
                continue
            position = new[j1][1] if j1 < len(new) else len(self.current.text)
            self._block(old[i1:i2], new[j1:j2], position)
        if speakers:
            self._compare_speakers()

    def _block(self, old: list[_Word], new: list[_Word], position: int) -> None:
        if _is_abbreviation([w for w, _, _ in old], [w for w, _, _ in new]):
            self.punctuation += Punctuation(abbreviations=1)
            return
        self._words(old, new, position)

    def _words(
        self,
        old: list[tuple[str, int, int]],
        new: list[tuple[str, int, int]],
        position: int,
    ) -> None:
        pairs, extra_old, extra_new = align_words(
            [word for word, _, _ in old], [word for word, _, _ in new]
        )
        for i, j in pairs:
            self.matched.append((old[i][1], new[j][1]))
            self._word(old[i][0], *new[j])
        for run in runs(extra_new):
            text = " ".join(new[j][0] for j in run)
            self.added.append(Phrase("", text, new[run[0]][1]))
        for run in runs(extra_old):
            text = " ".join(old[i][0] for i in run)
            self.removed.append(Phrase(text, "", position))

    def _word(self, original: str, corrected: str, start: int, end: int) -> None:
        superscript = _superscript(self.current, start, end)
        if original[:1].isupper() and corrected[:1].islower():
            # Zdanie małą literą - osobno od poprawki zapisu słowa.
            self.punctuation += Punctuation(lowercased=1)
            original = original[:1].lower() + original[1:]
        if original == corrected and not superscript:
            return
        if original.casefold() == corrected.casefold() and original != corrected:
            return
        correction = Correction(original, corrected, superscript)
        if rewritten(original, corrected) or (
            change_of(correction) is None and original != corrected
        ):
            self.phrases.append(Phrase(original, corrected, start))
        else:
            self.corrections.append(Located(correction, start))

    def _compare_speakers(self) -> None:
        """Mówcy akapitów, które w obu wersjach zaczyna ta sama para słów."""
        a_text, b_text = self.baseline.text, self.current.text
        b_spans = paragraph_spans(b_text)
        seen: set[int] = set()
        for a_start, b_start in self.matched:
            if not (
                _paragraph_start(a_text, a_start) and _paragraph_start(b_text, b_start)
            ):
                continue
            a_index = a_text.count("\n", 0, a_start)
            b_index = b_text.count("\n", 0, b_start)
            before = self.baseline.paragraph_speakers.get(a_index)
            after = self.current.paragraph_speakers.get(b_index)
            if before != after and b_index not in seen:
                seen.add(b_index)
                start, end = b_spans[b_index]
                self.speakers.append(
                    SpeakerEdit(b_index, start, b_text[start:end], before, after)
                )


def _paragraph_start(text: str, position: int) -> bool:
    """Słowo zaczyna akapit (przed nim w akapicie są tylko odstępy i znaki)."""
    line_start = text.rfind("\n", 0, position) + 1
    return not _WORD_RE.search(text, line_start, position)


def extract_edits(baseline: Version, current: Version, speakers: bool = True) -> Edits:
    """Różnice szkicu ``baseline`` i bieżącego tekstu ``current``.

    ``speakers`` False - bez porównania mówców (szkic odtworzony ich nie ma).
    """
    collector = _Collector(baseline, current)
    collector.compare(speakers)
    return Edits(
        len(_WORD_RE.findall(baseline.text)),
        tuple(collector.corrections),
        tuple(collector.phrases),
        tuple(collector.added),
        tuple(collector.removed),
        collector.punctuation,
        tuple(collector.speakers),
    )


# --- wnioski ------------------------------------------------------------------


@dataclass(frozen=True)
class RuleInsight:
    """Propozycja reguły z poprawkami (miejsca w tekście) i niepoprawionymi
    dopasowaniami wzorca w bieżącym tekście (``unmatched``)."""

    candidate: Candidate
    places: tuple[Located, ...]
    unmatched: int
    dismissed: bool = False


@dataclass(frozen=True)
class Repeated:
    """Powtarzająca się wymiana albo wstawka: tekst, liczba, miejsca."""

    original: str
    corrected: str
    count: int
    positions: tuple[int, ...]
    projects: int = 1

    @property
    def text(self) -> str:
        return self.corrected or self.original


@dataclass(frozen=True)
class DraftInsights:
    """Wnioski z poprawek jednej transkrypcji."""

    edits: Edits
    rules: tuple[RuleInsight, ...] = ()
    words: tuple[Repeated, ...] = ()
    added: tuple[Repeated, ...] = ()
    removed: tuple[Repeated, ...] = ()
    hidden_rules: int = 0

    @property
    def punctuation(self) -> Punctuation:
        return self.edits.punctuation

    @property
    def speakers(self) -> tuple[SpeakerEdit, ...]:
        return self.edits.speakers


def repeated(
    phrases: Iterable[Phrase], min_repeats: int = WORD_MIN_REPEATS
) -> tuple[Repeated, ...]:
    """Te same wymiany (albo wstawki) zgrupowane, od najczęstszej."""
    groups: dict[tuple[str, str], list[Phrase]] = {}
    for phrase in phrases:
        key = (phrase.original.casefold(), phrase.corrected.casefold())
        groups.setdefault(key, []).append(phrase)
    found = [
        Repeated(
            items[0].original,
            items[0].corrected,
            len(items),
            tuple(item.position for item in items),
        )
        for items in groups.values()
        if len(items) >= min_repeats
    ]
    return tuple(sorted(found, key=lambda item: (-item.count, item.text.casefold())))


def change_key(item: Located) -> DismissedKey | None:
    """Klucz zmiany poprawki (None - poprawka nie nadaje się na regułę)."""
    change = change_of(item.correction)
    return None if change is None else change.key


def _unmatched(rule: PhoneticRule, text: str) -> int:
    """Ile miejsc bieżącego tekstu reguła zmieniłaby (niepoprawione poprawki)."""
    return sum(
        1 for suggestion in propose(text, (rule,)) if suggestion.code == rule.code
    )


def rule_insights(
    corrections: Sequence[Located],
    rules: Sequence[PhoneticRule],
    dismissed: Iterable[DismissedKey] = (),
    min_repeats: int = MIN_REPEATS,
    text: str = "",
) -> list[RuleInsight]:
    """Propozycje reguł (także odrzucone - z ``dismissed`` True)."""
    skipped = frozenset(dismissed)
    found = candidates(
        (item.correction for item in corrections), rules, (), min_repeats
    )
    insights = []
    for candidate in found:
        key = candidate.change.key
        places = tuple(item for item in corrections if change_key(item) == key)
        insights.append(
            RuleInsight(
                candidate,
                places,
                _unmatched(candidate.rule, text) if text else 0,
                key in skipped,
            )
        )
    return insights


def draft_insights(
    baseline: Version,
    current: Version,
    rules: Sequence[PhoneticRule],
    dismissed: Iterable[DismissedKey] = (),
    min_repeats: int = MIN_REPEATS,
    speakers: bool = True,
) -> DraftInsights:
    """Wnioski z poprawek szkicu ``baseline`` w bieżącym tekście ``current``."""
    edits = extract_edits(baseline, current, speakers)
    insights = rule_insights(
        edits.corrections, rules, dismissed, min_repeats, current.text
    )
    keys = {change_key(item) for item in edits.corrections} - {None}
    shown = {insight.candidate.change.key for insight in insights}
    hidden = len(keys - shown)
    return DraftInsights(
        edits,
        tuple(insights),
        repeated(edits.phrases),
        repeated(edits.added),
        repeated(edits.removed),
        hidden,
    )


def suggested_settings(
    added: int, punctuation: Punctuation, *, verbatim: bool, plain: bool, expand: bool
) -> tuple[str, ...]:
    """Ustawienia zapisu szkicu, które poprawki podpowiadają włączyć.

    Nazwy pól ``AsrSettings``: ``verbatim`` (dużo dopisanych wstawek),
    ``lowercase_plain`` (usuwana interpunkcja, zdania małą literą),
    ``expand_abbreviations`` (rozwijane skróty).
    """
    found = []
    if not verbatim and added >= VERBATIM_MIN_ADDED:
        found.append("verbatim")
    if not plain and (
        punctuation.removed >= PLAIN_MIN_PUNCTUATION
        or punctuation.lowercased >= PLAIN_MIN_LOWERCASED
    ):
        found.append("lowercase_plain")
    if not expand and punctuation.abbreviations >= ABBREVIATIONS_MIN:
        found.append("expand_abbreviations")
    return tuple(found)


__all__ = [
    "DraftInsights",
    "Edits",
    "Located",
    "Phrase",
    "Punctuation",
    "Repeated",
    "RuleInsight",
    "SpeakerEdit",
    "change_key",
    "draft_insights",
    "extract_edits",
    "repeated",
    "rule_insights",
    "suggested_settings",
]
