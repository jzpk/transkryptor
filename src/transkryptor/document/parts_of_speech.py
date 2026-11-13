"""Części mowy słów transkrypcji według analizatora Morfeusz 2 (zgłoszenie #35).

Morfeusz 2 ze słownikiem SGJP (licencja BSD-2-Clause) podaje wszystkie
możliwe interpretacje słowa bez kontekstu. Słowo dostaje jedną część mowy:
interpretacje z kwalifikatorem dziedziny lub stylu (np. „do” jako nuta,
„muz.”) odpadają, gdy są inne, a z pozostałych wygrywa pierwsza część mowy
w kolejności ``PRIORITY``. Wyrazy niesamodzielne są pierwsze, a rzeczownik
ostatni, bo słownik zna wiele rzadkich form rzeczownikowych (np. „szybko”
jako wołacz od „szybka”). Bez kontekstu zdarzają się pomyłki („piec” jest
czasownikiem). Słowa spoza słownika (formy gwarowe, zapis fonetyczny) nie
mają części mowy.

Znaczniki Morfeusza są grupowane w tradycyjne części mowy: imiesłowy
należą do czasownika, odsłownik (``ger``) - do rzeczownika, a zaimki
przymiotne (np. „ten”) Morfeusz oznacza jako przymiotniki. Analiza jednego
słowa jest zapamiętywana, więc ponowne przejście po tekście jest tanie.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum

import regex

# Słowo: litery wraz ze znakami łączącymi (diakrytyki zapisu fonetycznego).
_WORD_RE = regex.compile(r"[\p{L}\p{M}]+")


class PartOfSpeech(StrEnum):
    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    PRONOUN = "pronoun"
    NUMERAL = "numeral"
    PREPOSITION = "preposition"
    CONJUNCTION = "conjunction"
    PARTICLE = "particle"
    INTERJECTION = "interjection"


# Klasa gramatyczna Morfeusza (pierwszy człon znacznika) → część mowy.
TAG_CLASSES: dict[str, PartOfSpeech] = {
    **dict.fromkeys(("subst", "depr", "ger"), PartOfSpeech.NOUN),
    **dict.fromkeys(
        (
            "fin",
            "bedzie",
            "praet",
            "impt",
            "imps",
            "inf",
            "pcon",
            "pant",
            "pact",
            "ppas",
            "winien",
        ),
        PartOfSpeech.VERB,
    ),
    **dict.fromkeys(("adj", "adja", "adjp", "adjc"), PartOfSpeech.ADJECTIVE),
    "adv": PartOfSpeech.ADVERB,
    **dict.fromkeys(("ppron12", "ppron3", "siebie"), PartOfSpeech.PRONOUN),
    **dict.fromkeys(("num", "numcol"), PartOfSpeech.NUMERAL),
    "prep": PartOfSpeech.PREPOSITION,
    **dict.fromkeys(("conj", "comp"), PartOfSpeech.CONJUNCTION),
    **dict.fromkeys(("part", "qub"), PartOfSpeech.PARTICLE),
    "interj": PartOfSpeech.INTERJECTION,
}

# Kolejność wyboru części mowy słowa wieloznacznego.
PRIORITY = (
    PartOfSpeech.PREPOSITION,
    PartOfSpeech.CONJUNCTION,
    PartOfSpeech.PARTICLE,
    PartOfSpeech.INTERJECTION,
    PartOfSpeech.PRONOUN,
    PartOfSpeech.VERB,
    PartOfSpeech.ADJECTIVE,
    PartOfSpeech.NUMERAL,
    PartOfSpeech.ADVERB,
    PartOfSpeech.NOUN,
)

# Interpretacje słowa: znacznik (np. ``"fin:sg:ter:imperf"``) i kwalifikatory
# (np. ``["muz."]``).
Interpretation = tuple[str, Sequence[str]]
Analyser = Callable[[str], Iterable[Interpretation]]


class AnalyserUnavailable(RuntimeError):
    """Biblioteka Morfeusz 2 nie jest dostępna w tej instalacji."""


def morfeusz_analyser() -> Analyser:
    """Analizator Morfeusz 2 ze słownikiem SGJP (wczytanie trwa ułamek sekundy)."""
    try:
        import morfeusz2
    except ImportError as error:
        raise AnalyserUnavailable(str(error)) from error
    morfeusz = morfeusz2.Morfeusz()

    def analyse(word: str) -> list[Interpretation]:
        # Wynik: (od, do, (forma, lemat, znacznik, nazwy, kwalifikatory)).
        return [(found[2], found[4]) for _, _, found in morfeusz.analyse(word)]

    return analyse


class PartOfSpeechTagger:
    """Części mowy słów tekstu, z pamięcią analiz pojedynczych słów."""

    def __init__(self, analyser: Analyser) -> None:
        self._analyse = analyser
        self._cache: dict[str, PartOfSpeech | None] = {}

    def part_of(self, word: str) -> PartOfSpeech | None:
        """Część mowy słowa; None - słowo spoza słownika albo interpunkcja."""
        if word not in self._cache:
            self._cache[word] = _choose(list(self._analyse(word)))
        return self._cache[word]

    def spans(
        self, text: str, wanted: Sequence[PartOfSpeech]
    ) -> list[tuple[int, int, PartOfSpeech]]:
        """Słowa tekstu należące do wybranych części mowy."""
        if not wanted:
            return []
        found = []
        for match in _WORD_RE.finditer(text):
            part = self.part_of(match.group())
            if part is not None and part in wanted:
                found.append((match.start(), match.end(), part))
        return found


def _choose(interpretations: list[Interpretation]) -> PartOfSpeech | None:
    """Jedna część mowy z interpretacji (bez rzadkich, gdy są inne)."""
    plain = [entry for entry in interpretations if not entry[1]]
    parts = {
        TAG_CLASSES[tag.split(":", 1)[0]]
        for tag, _ in plain or interpretations
        if tag.split(":", 1)[0] in TAG_CLASSES
    }
    return next((part for part in PRIORITY if part in parts), None)
