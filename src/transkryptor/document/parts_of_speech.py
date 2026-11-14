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
przymiotne (np. „ten”) Morfeusz oznacza jako przymiotniki. Zaimki
rzeczowne (np. „kto”, „nic”, „wszystko”) Morfeusz oznacza jako rzeczowniki
(``subst``), więc rozpoznajemy je po lemacie (``NOUN_PRONOUN_LEMMAS``,
zgłoszenie #53). Analiza jednego
słowa jest zapamiętywana, więc ponowne przejście po tekście jest tanie.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum

import regex

# Słowo: litery wraz ze znakami łączącymi (diakrytyki zapisu fonetycznego).
WORD_RE = regex.compile(r"[\p{L}\p{M}]+")


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


# Kolor każdej części mowy (``#rrggbb``): w edytorze półprzezroczyste
# podświetlenie, w eksporcie tło słowa (``paper_color``).
POS_COLORS: dict[PartOfSpeech, str] = {
    PartOfSpeech.NOUN: "#4a9df8",
    PartOfSpeech.VERB: "#f0506e",
    PartOfSpeech.ADJECTIVE: "#3cbf6a",
    PartOfSpeech.ADVERB: "#ff8a2a",
    PartOfSpeech.PRONOUN: "#9b6bff",
    PartOfSpeech.NUMERAL: "#14b8b0",
    PartOfSpeech.PREPOSITION: "#a0785a",
    PartOfSpeech.CONJUNCTION: "#8a94a6",
    PartOfSpeech.PARTICLE: "#e0b400",
    PartOfSpeech.INTERJECTION: "#e05cd0",
}
# Krycie podświetlenia (0-255) - to samo w edytorze i na papierze.
POS_ALPHA = 90


def paper_color(part: PartOfSpeech) -> str:
    """Kolor części mowy nałożony z krycia ``POS_ALPHA`` na białe tło."""
    base = POS_COLORS[part].lstrip("#")
    channels = (int(base[i : i + 2], 16) for i in (0, 2, 4))
    mixed = (255 - (255 - value) * POS_ALPHA // 255 for value in channels)
    return "#" + "".join(f"{value:02x}" for value in mixed)


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

# Lematy zaimków rzeczownych, które Morfeusz oznacza jako ``subst``.
NOUN_PRONOUN_LEMMAS = frozenset(
    (
        "kto",
        "ktoś",
        "ktokolwiek",
        "ktosik",
        "któż",
        "nikt",
        "co",
        "coś",
        "cokolwiek",
        "cosik",
        "cóż",
        "nic",
        "wszystko",
        "wszyscy",
        "to",
        "tamto",
        "owo",
    )
)

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

# Interpretacje słowa: znacznik (np. ``"fin:sg:ter:imperf"``), kwalifikatory
# (np. ``["muz."]``) i lemat (np. ``"co:S"`` - po dwukropku rozróżnienie
# homonimów).
Interpretation = tuple[str, Sequence[str], str]
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
        return [
            (found[2], found[4], found[1]) for _, _, found in morfeusz.analyse(word)
        ]

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
        for match in WORD_RE.finditer(text):
            part = self.part_of(match.group())
            if part is not None and part in wanted:
                found.append((match.start(), match.end(), part))
        return found


def _choose(interpretations: list[Interpretation]) -> PartOfSpeech | None:
    """Jedna część mowy z interpretacji (bez rzadkich, gdy są inne)."""
    plain = [entry for entry in interpretations if not entry[1]]
    parts = {_part(tag, lemma) for tag, _, lemma in plain or interpretations}
    return next((part for part in PRIORITY if part in parts), None)


def _part(tag: str, lemma: str) -> PartOfSpeech | None:
    """Część mowy jednej interpretacji; zaimek rzeczowny zamiast rzeczownika."""
    part = TAG_CLASSES.get(tag.split(":", 1)[0])
    if part is PartOfSpeech.NOUN and lemma.split(":", 1)[0] in NOUN_PRONOUN_LEMMAS:
        return PartOfSpeech.PRONOUN
    return part
