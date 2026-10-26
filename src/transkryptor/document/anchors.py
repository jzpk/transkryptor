"""Kotwice czasowe: powiązanie fragmentów tekstu z czasem nagrania (bez Qt).

Kotwica to zakres tekstu ``[start, end)`` (pozycje Pythona) z czasem
``start_ms``-``end_ms`` w nagraniu. Źródła:

- ``segment`` - segment szkicu ASR;
- ``word`` - słowo szkicu ASR z prawdopodobieństwem (``probability``);
  ``edited`` oznacza, że użytkownik poprawił słowo (przestaje być niepewne);
- ``manual`` - ręczny znacznik czasu, punktowy (``start == end``).

Moduł buduje kotwice szkicu (:func:`build_draft`), wyszukuje kotwicę dla
pozycji w tekście (:func:`anchor_at`) i aktywny segment dla pozycji
odtwarzania (:class:`TimeIndex`). Kotwice przesuwające się z edycją śledzi
warstwa UI (kursory edytora); tu są tylko dane w chwili zapisu i odczytu.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

SEGMENT = "segment"
WORD = "word"
MANUAL = "manual"
SOURCES = (SEGMENT, WORD, MANUAL)


@dataclass(frozen=True)
class Anchor:
    start: int
    end: int
    start_ms: int
    end_ms: int
    source: str = SEGMENT
    probability: float | None = None
    edited: bool = False

    @property
    def is_point(self) -> bool:
        return self.start == self.end

    def shifted(self, offset: int) -> Anchor:
        """Kotwica przesunięta o ``offset`` znaków."""
        return replace(self, start=self.start + offset, end=self.end + offset)

    def is_uncertain(self, threshold: float) -> bool:
        """Czy to niepoprawione słowo o pewności poniżej progu."""
        return (
            self.source == WORD
            and not self.edited
            and self.probability is not None
            and self.probability < threshold
        )


class TimedWord(Protocol):
    @property
    def start_s(self) -> float: ...
    @property
    def end_s(self) -> float: ...
    @property
    def text(self) -> str: ...
    @property
    def probability(self) -> float: ...


class TimedSegment(Protocol):
    """Segment ASR; opcjonalny atrybut ``words`` to słowa z czasami."""

    @property
    def start_s(self) -> float: ...
    @property
    def end_s(self) -> float: ...
    @property
    def text(self) -> str: ...


def to_ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def build_draft(
    text: str,
    segments: Iterable[TimedSegment],
    normalize: Callable[[str], str] = lambda value: value,
) -> tuple[str, list[Anchor]]:
    """Tekst szkicu i kotwice segmentów oraz słów (pozycje względem szkicu).

    Szkic to ``normalize(text)`` - tak jak bez kotwic. Segmenty i słowa są
    odszukiwane w nim kolejno, każdy za poprzednim; fragment, którego nie da
    się odnaleźć (np. normalizacja zmieniła granicę), zostaje bez kotwicy.
    """
    draft = normalize(text)
    anchors: list[Anchor] = []
    cursor = 0
    for segment in segments:
        piece = normalize(segment.text).strip()
        if not piece:
            continue
        found = draft.find(piece, cursor)
        if found < 0:
            continue
        end = found + len(piece)
        anchors.append(
            Anchor(found, end, to_ms(segment.start_s), to_ms(segment.end_s), SEGMENT)
        )
        word_cursor = found
        words: Sequence[TimedWord] = getattr(segment, "words", ())
        for word in words:
            token = normalize(word.text).strip()
            if not token:
                continue
            word_start = draft.find(token, word_cursor, end)
            if word_start < 0:
                continue
            word_end = word_start + len(token)
            anchors.append(
                Anchor(
                    word_start,
                    word_end,
                    to_ms(word.start_s),
                    to_ms(word.end_s),
                    WORD,
                    probability=round(float(word.probability), 3),
                )
            )
            word_cursor = word_end
        cursor = end
    return draft, anchors


def anchor_at(
    anchors: Iterable[Anchor], position: int, word_level: bool = True
) -> Anchor | None:
    """Kotwica dla pozycji w tekście.

    Najpierw słowo obejmujące pozycję (``word_level``), a dalej segment albo
    znacznik ręczny o największym początku nie większym niż pozycja - czyli
    zawierający ją albo poprzedzający (znacznik w środku segmentu wygrywa
    z jego początkiem).
    """
    best: Anchor | None = None
    for anchor in anchors:
        if anchor.source == WORD:
            if word_level and anchor.start <= position <= anchor.end:
                return anchor
            continue
        if anchor.start > position:
            continue
        if (
            best is None
            or anchor.start > best.start
            or (anchor.start == best.start and anchor.source == MANUAL)
        ):
            best = anchor
    return best


def time_span(
    anchors: Iterable[Anchor], start: int, end: int, prefer_words: bool = True
) -> tuple[int, int] | None:
    """Czas nagrania (ms) fragmentu tekstu ``[start, end)`` z jego kotwic.

    Słowa z czasem są dokładniejsze niż segment, w którym leżą - gdy
    fragment je obejmuje, liczą się tylko one (``prefer_words``; bez tego -
    wszystkie kotwice, np. dla całego akapitu). None - fragment nie ma
    kotwic czasowych albo ich czas jest pusty.
    """
    touching = [
        anchor
        for anchor in anchors
        if (anchor.start < end and anchor.end > start)
        or (anchor.is_point and start <= anchor.start <= end)
    ]
    words = [a for a in touching if a.source == WORD] if prefer_words else []
    spans = [(anchor.start_ms, anchor.end_ms) for anchor in words or touching]
    if not spans:
        return None
    first = min(span[0] for span in spans)
    last = max(span[1] for span in spans)
    return (first, last) if last > first else None


class TimeIndex:
    """Segmenty posortowane po czasie: aktywny segment dla pozycji nagrania."""

    def __init__(self, anchors: Sequence[Anchor]) -> None:
        order = sorted(
            (i for i, anchor in enumerate(anchors) if anchor.source == SEGMENT),
            key=lambda i: anchors[i].start_ms,
        )
        self._indices = order
        self._starts = [anchors[i].start_ms for i in order]
        self._ends = [anchors[i].end_ms for i in order]

    def active_at(self, position_ms: int) -> int | None:
        """Indeks (w liście wejściowej) segmentu trwającego w ``position_ms``."""
        slot = bisect_right(self._starts, position_ms) - 1
        if slot < 0 or position_ms >= self._ends[slot]:
            return None
        return self._indices[slot]


def check_anchor(anchor: Anchor, text_length: int) -> None:
    """``ValueError``, gdy kotwica nie pasuje do tekstu o danej długości."""
    if anchor.source not in SOURCES:
        raise ValueError(f"nieznane źródło kotwicy: {anchor.source}")
    if not 0 <= anchor.start <= anchor.end <= text_length:
        raise ValueError("kotwica poza tekstem")
    if not 0 <= anchor.start_ms <= anchor.end_ms:
        raise ValueError("nieprawidłowy czas kotwicy")
    if anchor.source == MANUAL and not anchor.is_point:
        raise ValueError("znacznik ręczny musi być punktem")
    if anchor.source != MANUAL and anchor.is_point:
        raise ValueError("pusta kotwica")
