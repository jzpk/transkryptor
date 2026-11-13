"""Układ szkicu „pytanie - odpowiedź” według znaków zapytania (zgłoszenie #41).

Wywiad gwarowy ma stały układ: badacz pyta (także o metryczkę: „Miejscowość?
Imię i nazwisko?”), informator odpowiada. :func:`question_answer_layout`
dzieli wynik ASR na zdania i nadaje im mówców jak podział na mówców: zdanie
zakończone znakiem zapytania (albo uznane za pytanie przez ``is_question``,
np. z kwestionariusza) dostaje głos 0 - badacza, pozostałe głos 1 -
informatora. Fatyczne „nie?”, „co nie?”, „prawda?” na końcu wypowiedzi
(``asr/phatic.py``) nie robią z niej pytania. Szkic ma wtedy osobny wers
na każde pytanie i każdą odpowiedź, ze znacznikiem czasu początku zdania.

Zdania wyznaczają słowa z czasami (także ponad granicą segmentów Whispera);
segment bez słów jest dzielony na zdania z czasem proporcjonalnym do
długości tekstu.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

import regex

from transkryptor.asr.engine import SegmentResult, TranscriptionResult, WordResult
from transkryptor.asr.phatic import ends_with_phatic_tag
from transkryptor.document.questionnaire import QuestionMatcher

QUESTION = 0
ANSWER = 1

# Koniec zdania: . ? ! … (także „...”), za nimi mogą stać cudzysłów i nawias.
_SENTENCE_END_RE = regex.compile(r"[.?!…][\"”)\]]*\s*$")
_QUESTION_END_RE = regex.compile(r"\?[\"”)\]]*\s*$")
_SPLIT_RE = regex.compile(r"(?<=[.?!…][\"”)\]]*)(?=\s)")

IsQuestion = Callable[[str], bool]


def ends_with_question(sentence: str) -> bool:
    """Zdanie ze znakiem zapytania na końcu, ale bez fatycznego „nie?”."""
    return bool(_QUESTION_END_RE.search(sentence)) and not ends_with_phatic_tag(
        sentence
    )


def question_detector(questions: Sequence[str]) -> IsQuestion:
    """Pytanie: znak zapytania albo zdanie z kwestionariusza (zgł. #47)."""
    matcher = QuestionMatcher(questions)
    if not matcher:
        return ends_with_question

    def is_question(sentence: str) -> bool:
        if ends_with_question(sentence):
            return True
        return not ends_with_phatic_tag(sentence) and matcher.matches(sentence)

    return is_question


@dataclass(frozen=True)
class _Unit:
    """Najmniejszy kawałek z czasem: słowo albo zdanie segmentu bez słów."""

    start_s: float
    end_s: float
    text: str
    confidence: float
    words: tuple[WordResult, ...]


def question_answer_layout(
    result: TranscriptionResult, is_question: IsQuestion = ends_with_question
) -> TranscriptionResult:
    """Wynik ze zdaniami jako segmentami: pytania - głos 0, odpowiedzi - 1."""
    sentences = [
        _sentence_segment(units, is_question)
        for units in _sentences(_units(result.segments))
    ]
    if not sentences:
        return result
    return replace(result, segments=tuple(sentences))


def _units(segments: Iterable[SegmentResult]) -> Iterator[_Unit]:
    for segment in segments:
        if segment.words:
            for word in segment.words:
                yield _Unit(
                    word.start_s, word.end_s, word.text, segment.confidence, (word,)
                )
        else:
            yield from _split_segment(segment)


def _split_segment(segment: SegmentResult) -> Iterator[_Unit]:
    """Zdania segmentu bez słów, z czasem proporcjonalnym do długości."""
    pieces = [piece for piece in _SPLIT_RE.split(segment.text) if piece.strip()]
    total = sum(len(piece) for piece in pieces) or 1
    duration = segment.end_s - segment.start_s
    start = segment.start_s
    for piece in pieces:
        end = start + duration * len(piece) / total
        yield _Unit(start, end, piece, segment.confidence, ())
        start = end


def _sentences(units: Iterable[_Unit]) -> Iterator[list[_Unit]]:
    current: list[_Unit] = []
    for unit in units:
        if not unit.text.strip():
            continue
        current.append(unit)
        if _SENTENCE_END_RE.search(unit.text):
            yield current
            current = []
    if current:
        yield current


def _sentence_segment(units: list[_Unit], is_question: IsQuestion) -> SegmentResult:
    text = "".join(unit.text for unit in units)
    if not text.startswith(" "):
        text = " " + text.lstrip()
    speaker = QUESTION if is_question(text.strip()) else ANSWER
    return SegmentResult(
        start_s=units[0].start_s,
        end_s=units[-1].end_s,
        text=text,
        confidence=min(unit.confidence for unit in units),
        words=tuple(word for unit in units for word in unit.words),
        speaker=speaker,
    )


__all__ = [
    "ANSWER",
    "QUESTION",
    "ends_with_question",
    "question_answer_layout",
    "question_detector",
]
