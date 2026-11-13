"""Kwestionariusz wywiadu: lista pytań wczytana przed transkrypcją (zgłoszenie #47).

Badacz zadaje pytania z kwestionariusza (spisu pytań), więc zdanie podobne
do pytania z listy jest wypowiedzią badacza - także wtedy, gdy model nie
postawił znaku zapytania („Rok i miejsce urodzenia”). Układ szkicu
„pytanie - odpowiedź” (``asr/qa_layout.py``) korzysta z tego przez
:class:`QuestionMatcher`.

Plik kwestionariusza to tekst (.txt) albo dokument Word (.docx): jedno
pytanie w wierszu lub akapicie. Numeracja i punktory na początku są
pomijane, podobnie jak puste wiersze i nagłówki działów pisane wielkimi
literami („KOBIETA CIĘŻARNA”).
"""

from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher
from pathlib import Path

import regex

# Numeracja i punktory: „1.”, „1)”, „12 -”, „-”, „•”, „*”.
_PREFIX_RE = regex.compile(r"^\s*(?:\d+[.)]?\s*[-–—]?|[-•*–—])\s*")
_WORD_RE = regex.compile(r"\p{L}+")
# Zdanie jest pytaniem z listy, gdy jest prawie takie samo (podobieństwo
# napisów) albo zawiera prawie wszystkie słowa pytania i niewiele więcej -
# dłuższe zdanie ze słowami pytania to zwykle odpowiedź („Miejscowość
# Ocieszyn, gmina Oborniki”).
SIMILARITY = 0.8
COVERAGE = 0.8
MAX_EXTRA_WORDS_RATIO = 1.5
MIN_WORDS = 2


def parse_questionnaire(text: str) -> tuple[str, ...]:
    """Pytania z tekstu: wiersze bez numeracji, pustych wierszy i nagłówków."""
    return parse_lines(text.splitlines())


def parse_lines(lines: Iterable[str]) -> tuple[str, ...]:
    questions = []
    for line in lines:
        question = _PREFIX_RE.sub("", line).strip()
        letters = "".join(_WORD_RE.findall(question))
        if not letters or (len(letters) > 1 and letters.isupper()):
            continue
        questions.append(question)
    return tuple(questions)


def read_questionnaire(path: Path) -> tuple[str, ...]:
    """Pytania z pliku .docx (akapity) albo tekstowego (UTF-8 lub Windows-1250)."""
    if path.suffix.lower() == ".docx":
        import docx

        return parse_lines(p.text for p in docx.Document(str(path)).paragraphs)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1250", errors="replace")
    return parse_questionnaire(text)


def _words(text: str) -> list[str]:
    return [word.lower() for word in _WORD_RE.findall(text)]


class QuestionMatcher:
    """Czy zdanie szkicu jest (prawie) pytaniem z kwestionariusza."""

    def __init__(self, questions: Iterable[str]) -> None:
        self._questions = [
            (" ".join(words), set(words), len(words))
            for words in (_words(question) for question in questions)
            if len(words) >= MIN_WORDS
        ]

    def __bool__(self) -> bool:
        return bool(self._questions)

    def matches(self, sentence: str) -> bool:
        words = _words(sentence)
        if len(words) < MIN_WORDS:
            return False
        text, present = " ".join(words), set(words)
        for question, wanted, count in self._questions:
            if SequenceMatcher(None, text, question).ratio() >= SIMILARITY:
                return True
            covered = len(wanted & present) / len(wanted)
            if covered >= COVERAGE and len(words) <= count * MAX_EXTRA_WORDS_RATIO:
                return True
        return False
