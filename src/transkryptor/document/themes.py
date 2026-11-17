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

Kilka transkrypcji łączy :func:`combined_fields` (zgłoszenie #71): każde
źródło tekstu (:class:`TextSource`, np. wypowiedzi jednego informatora)
niesie nazwę informatora, a słowo pola zbiera nazwy tych, którzy go użyli.
:func:`speaker_sources` dzieli projekt na takie źródła.
"""

from __future__ import annotations

import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources

from transkryptor.document.parts_of_speech import WORD_RE, morfeusz_analyser
from transkryptor.document.speakers import Speaker, paragraph_spans
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
    """Lemat pola z liczbą wystąpień, formami z tekstu i informatorami.

    ``forms`` i ``speakers`` są w kolejności pierwszego użycia.
    """

    lemma: str
    count: int
    forms: tuple[str, ...]
    speakers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextSource:
    """Tekst (albo jego zakresy ``ranges``) i nazwa informatora - pusta: brak."""

    text: str
    ranges: Sequence[tuple[int, int]] | None = None
    speaker: str = ""


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
    return combined_fields([TextSource(text, ranges)], lemmatize, themes)


def combined_fields(
    sources: Iterable[TextSource],
    lemmatize: Lemmatizer = plain_lemmatizer,
    themes: Iterable[Theme] | None = None,
) -> list[ThemeSummary]:
    """Pola tematyczne wszystkich źródeł razem, z informatorami przy słowach."""
    themes = tuple(builtin_themes() if themes is None else themes)
    tally = _Tally(themes, lemmatize)
    for source in sources:
        for word in _words(source.text, source.ranges):
            tally.add(word, source.speaker)
    summaries = [tally.summary(theme) for theme in themes if tally.counts[theme.key]]
    return sorted(summaries, key=lambda summary: -summary.total)


class _Tally:
    """Liczniki lematów pól, form i informatorów podczas przeglądania słów."""

    def __init__(self, themes: Sequence[Theme], lemmatize: Lemmatizer) -> None:
        self._lemmatize = lemmatize
        self._by_lemma: dict[str, list[Theme]] = defaultdict(list)
        for theme in themes:
            for lemma in theme.lemmas:
                self._by_lemma[lemma].append(theme)
        self.counts: dict[str, Counter[str]] = defaultdict(Counter)
        self._forms: dict[tuple[str, str], dict[str, None]] = defaultdict(dict)
        self._speakers: dict[tuple[str, str], dict[str, None]] = defaultdict(dict)
        self._lemmas_of: dict[str, frozenset[str]] = {}

    def _lemmas(self, word: str) -> frozenset[str]:
        if word not in self._lemmas_of:
            lemmas = {lemma.casefold() for lemma in self._lemmatize(word)}
            lemmas.add(word.casefold())
            self._lemmas_of[word] = frozenset(
                lemma for lemma in lemmas if lemma in self._by_lemma
            )
        return self._lemmas_of[word]

    def add(self, word: str, speaker: str) -> None:
        for lemma in self._lemmas(word):
            for theme in self._by_lemma[lemma]:
                self.counts[theme.key][lemma] += 1
                self._forms[theme.key, lemma].setdefault(word.casefold())
                if speaker:
                    self._speakers[theme.key, lemma].setdefault(speaker)

    def summary(self, theme: Theme) -> ThemeSummary:
        ranked = sorted(
            self.counts[theme.key].items(), key=lambda item: (-item[1], item[0])
        )
        return ThemeSummary(
            theme,
            tuple(
                ThemeWord(
                    lemma,
                    count,
                    tuple(self._forms[theme.key, lemma]),
                    tuple(self._speakers[theme.key, lemma]),
                )
                for lemma, count in ranked
            ),
        )


def speaker_sources(
    text: str,
    assignments: Mapping[int, str],
    speakers: Iterable[Speaker],
    project: str,
) -> list[TextSource]:
    """Źródła projektu: wypowiedzi każdego informatora osobno.

    Informatora nazywa jego etykieta (ta sama osoba w kilku nagraniach
    łączy się w jedną), a bez etykiety - klucz i nazwa projektu
    („I (wywiad_1)”). Projekt bez akapitów informatorów to jedno źródło
    z całym tekstem i nazwą projektu.
    """
    informants = {speaker.key: speaker for speaker in speakers if speaker.is_informant}
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for index, span in enumerate(paragraph_spans(text)):
        key = assignments.get(index)
        if key in informants:
            spans[key].append(span)
    if not spans:
        return [TextSource(text, None, project)]
    return [
        TextSource(text, ranges, informants[key].label or f"{key} ({project})")
        for key, ranges in spans.items()
    ]


def _words(text: str, ranges: Sequence[tuple[int, int]] | None) -> Iterable[str]:
    pieces = [text] if ranges is None else [text[start:end] for start, end in ranges]
    for piece in pieces:
        for match in WORD_RE.finditer(piece):
            yield match.group()


__all__ = [
    "Lemmatizer",
    "Theme",
    "ThemeSummary",
    "TextSource",
    "ThemeWord",
    "builtin_themes",
    "combined_fields",
    "morfeusz_lemmatizer",
    "plain_lemmatizer",
    "speaker_sources",
    "thematic_fields",
]
