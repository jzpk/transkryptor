"""Odmiana form przez Morfeusza 2: przymiotnik zgodny z następnym słowem.

Rozwinięcie skrótu „tzw.” musi się zgadzać z określanym słowem („tak zwaną
myszkę”, „tak zwanego domu”). Forma imiesłowu jest wybierana z form
wygenerowanych przez Morfeusza tak, by liczba, przypadek i rodzaj zgadzały
się z pierwszą rzeczownikową albo przymiotnikową interpretacją słowa.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from transkryptor.document.parts_of_speech import AnalyserUnavailable

# Klasy, z którymi przymiotnik się uzgadnia.
_AGREEING_CLASSES = ("subst", "depr", "ger", "adj", "ppas", "pact")

# (forma, znacznik) - wynik analizy albo generowania jednego słowa.
Forms = Callable[[str], Iterable[tuple[str, str]]]


class Inflector:
    """Formy przymiotnikowe zgodne ze słowem (np. „zwaną” dla „myszkę”)."""

    def __init__(self, analyse: Forms, generate: Forms) -> None:
        self._analyse = analyse
        self._generate = generate

    def agreeing(self, lemma: str, word: str) -> str | None:
        """Forma imiesłowu ``lemma`` zgodna ze słowem; None - brak zgody."""
        target = self._agreement(word)
        if target is None:
            return None
        number, cases, genders = target
        for form, tag in self._generate(lemma):
            parts = tag.split(":")
            if parts[0] != "ppas" or "aff" not in parts or len(parts) < 4:
                continue
            if (
                parts[1] == number
                and cases & set(parts[2].split("."))
                and genders & set(parts[3].split("."))
            ):
                return form
        return None

    def _agreement(self, word: str) -> tuple[str, set[str], set[str]] | None:
        for _form, tag in self._analyse(word):
            parts = tag.split(":")
            if parts[0] in _AGREEING_CLASSES and len(parts) >= 4:
                return parts[1], set(parts[2].split(".")), set(parts[3].split("."))
        return None


def morfeusz_inflector() -> Inflector:
    """Odmiana Morfeuszem 2; ``AnalyserUnavailable``, gdy go nie ma."""
    try:
        import morfeusz2
    except ImportError as error:
        raise AnalyserUnavailable(str(error)) from error
    morfeusz = morfeusz2.Morfeusz()

    def analyse(word: str) -> list[tuple[str, str]]:
        return [(found[0], found[2]) for _, _, found in morfeusz.analyse(word)]

    def generate(lemma: str) -> list[tuple[str, str]]:
        return [(found[0], found[2]) for found in morfeusz.generate(lemma)]

    return Inflector(analyse, generate)
