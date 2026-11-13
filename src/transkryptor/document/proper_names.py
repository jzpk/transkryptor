"""Rozpoznawanie nazw własnych Morfeuszem 2 (wielka litera w szkicu).

Szkic zapisany małymi literami (zgłoszenie #37) obniża pierwsze słowo zdania,
ale nazwy własne zostają wielką literą („w Maniewie”, „Poznań”). Słowo jest
traktowane jako możliwa nazwa własna, gdy wszystkie jego interpretacje mają
lemat od wielkiej litery, gdy któraś jest imieniem albo nazwą geograficzną
(„Poznań”, choć to też forma „poznanie”), albo gdy słowa nie ma w słowniku
(np. nazwa wsi, forma gwarowa) - wtedy bezpieczniej zostawić zapis modelu.
Samo nazwisko nie wystarcza: „Rok” i „Rolnik” to zwykle zwykłe słowa.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from transkryptor.document.parts_of_speech import AnalyserUnavailable

# Interpretacje słowa: (lemat, znacznik, kwalifikatory nazw).
Lemmas = Callable[[str], Iterable[tuple[str, str, Sequence[str]]]]
# Kwalifikatory Morfeusza rozstrzygające o nazwie własnej.
STRONG_NAMES = frozenset({"imię", "nazwa_geograficzna"})


class ProperNames:
    """Czy słowo pisane wielką literą może być nazwą własną."""

    def __init__(self, analyse: Lemmas) -> None:
        self._analyse = analyse
        self._cache: dict[str, bool] = {}

    def may_be_proper(self, word: str) -> bool:
        if word not in self._cache:
            self._cache[word] = self._check(word)
        return self._cache[word]

    def _check(self, word: str) -> bool:
        known = [
            (lemma, names)
            for lemma, tag, names in self._analyse(word)
            if not tag.startswith("ign")
        ]
        if not known:
            return True
        if all(lemma[:1].isupper() for lemma, _ in known):
            return True
        return any(STRONG_NAMES & set(names) for _, names in known)


def morfeusz_proper_names() -> ProperNames:
    """Nazwy własne według Morfeusza 2; ``AnalyserUnavailable``, gdy go nie ma."""
    try:
        import morfeusz2
    except ImportError as error:
        raise AnalyserUnavailable(str(error)) from error
    morfeusz = morfeusz2.Morfeusz()

    def analyse(word: str) -> list[tuple[str, str, Sequence[str]]]:
        return [
            (found[1], found[2], found[3]) for _, _, found in morfeusz.analyse(word)
        ]

    return ProperNames(analyse)
