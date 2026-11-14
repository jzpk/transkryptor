"""Pola tematyczne: słowa kluczowe wywiadu pogrupowane w tematy (zgłoszenie #51).

Słownik pól (``document/data/themes.toml``) przypisuje lematy tematom
(rolnictwo, dom, chrzest, pogrzeb…). Słowa tekstu są sprowadzane do lematów
(Morfeusz 2, :func:`morfeusz_lemmatizer`; bez niego - sama forma słowa),
a każde wystąpienie lematu z pola liczy się do tego pola. Wynik to pola
uporządkowane od najczęstszego, w każdym - słowa z liczbą wystąpień
i formami z tekstu. Tabela wyniku (:func:`themes_table`) trafia do CSV
albo XLSX jak tabele korpusu.

Gdy transkrypcja ma mówców, liczą się tylko wypowiedzi informatorów - pola
tematyczne opisują to, o czym mówią respondenci, nie pytania badacza.
"""

from __future__ import annotations

import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources

from transkryptor.document.parts_of_speech import WORD_RE, morfeusz_analyser
from transkryptor.notation.rules import localized

THEMES_SOURCE = "themes.toml"

# Słowo → jego możliwe lematy (bez kontekstu).
Lemmatizer = Callable[[str], Iterable[str]]


@dataclass(frozen=True)
class Theme:
    """Pole tematyczne: klucz, nazwa w językach interfejsu i lematy."""

    key: str
    label: Mapping[str, str]
    lemmas: frozenset[str]

    @property
    def label_text(self) -> str:
        return localized(self.label)


@dataclass(frozen=True)
class ThemeWord:
    """Lemat pola z liczbą wystąpień i formami z tekstu (w kolejności)."""

    lemma: str
    count: int
    forms: tuple[str, ...]


@dataclass(frozen=True)
class ThemeSummary:
    """Pole tematyczne obecne w tekście: słowa od najczęstszego."""

    theme: Theme
    words: tuple[ThemeWord, ...]

    @property
    def total(self) -> int:
        return sum(word.count for word in self.words)


@cache
def builtin_themes() -> tuple[Theme, ...]:
    """Pola tematyczne wbudowane w pakiet (wczytywane raz)."""
    raw = (
        resources.files("transkryptor.document")
        .joinpath("data", THEMES_SOURCE)
        .read_text(encoding="utf-8")
    )
    return tuple(
        Theme(
            key=entry["key"],
            label=dict(entry["label"]),
            lemmas=frozenset(lemma.casefold() for lemma in entry["lemmas"]),
        )
        for entry in tomllib.loads(raw).get("theme", [])
    )


def plain_lemmatizer(word: str) -> list[str]:
    """Bez analizatora: lematem jest sama forma słowa."""
    return [word]


def morfeusz_lemmatizer() -> Lemmatizer:
    """Lematy Morfeusza 2 (``AnalyserUnavailable``, gdy go brak)."""
    analyse = morfeusz_analyser()

    def lemmatize(word: str) -> list[str]:
        # Lemat Morfeusza ma po dwukropku rozróżnienie homonimów („co:S”).
        return [lemma.split(":", 1)[0] for _, _, lemma in analyse(word)]

    return lemmatize


def thematic_fields(
    text: str,
    lemmatize: Lemmatizer = plain_lemmatizer,
    ranges: Sequence[tuple[int, int]] | None = None,
    themes: Iterable[Theme] | None = None,
) -> list[ThemeSummary]:
    """Pola tematyczne słów tekstu (albo tylko zakresów ``ranges``)."""
    themes = tuple(builtin_themes() if themes is None else themes)
    by_lemma: dict[str, list[Theme]] = defaultdict(list)
    for theme in themes:
        for lemma in theme.lemmas:
            by_lemma[lemma].append(theme)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    forms: dict[tuple[str, str], dict[str, None]] = defaultdict(dict)
    lemmas_of: dict[str, frozenset[str]] = {}
    for word in _words(text, ranges):
        if word not in lemmas_of:
            lemmas = {lemma.casefold() for lemma in lemmatize(word)}
            lemmas.add(word.casefold())
            lemmas_of[word] = frozenset(lemma for lemma in lemmas if lemma in by_lemma)
        for lemma in lemmas_of[word]:
            for theme in by_lemma[lemma]:
                counts[theme.key][lemma] += 1
                forms[theme.key, lemma].setdefault(word.casefold())
    summaries = [
        ThemeSummary(
            theme,
            tuple(
                ThemeWord(lemma, count, tuple(forms[theme.key, lemma]))
                for lemma, count in sorted(
                    counts[theme.key].items(), key=lambda item: (-item[1], item[0])
                )
            ),
        )
        for theme in themes
        if counts[theme.key]
    ]
    return sorted(summaries, key=lambda summary: -summary.total)


def _words(text: str, ranges: Sequence[tuple[int, int]] | None) -> Iterable[str]:
    pieces = [text] if ranges is None else [text[start:end] for start, end in ranges]
    for piece in pieces:
        for match in WORD_RE.finditer(piece):
            yield match.group()


__all__ = [
    "Lemmatizer",
    "Theme",
    "ThemeSummary",
    "ThemeWord",
    "builtin_themes",
    "morfeusz_lemmatizer",
    "plain_lemmatizer",
    "thematic_fields",
]
