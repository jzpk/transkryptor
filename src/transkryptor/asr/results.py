"""Wynik transkrypcji ASR i szkic do edytora (bez Qt).

Klasy wyników trafiają przez pickle z procesu roboczego (``asr/worker.py``)
do UI i do projektu, więc moduł nie zależy od backendu ani modelu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Najdłuższy wers szkicu (w sekundach nagrania) - wers zaczyna się
# znacznikiem czasu, by tekst i eksport nie były jednym blokiem.
DRAFT_LINE_SECONDS = 30.0


@dataclass(frozen=True)
class WordResult:
    """Słowo hipotezy z czasem i prawdopodobieństwem Whispera (0.0-1.0).

    ``text`` zawiera spację wiodącą jak w Whisperze (``" kota"``).
    """

    start_s: float
    end_s: float
    text: str
    probability: float


@dataclass(frozen=True)
class SegmentResult:
    """Fragment hipotezy z czasem i przybliżoną pewnością (0.0-1.0).

    ``words`` - słowa z czasami, gdy transkrypcja liczyła je
    (``DecodingOptions.word_timestamps``). ``speaker`` - numer mówcy
    z diaryzacji (od 0, w kolejności pojawiania się); None bez diaryzacji.
    """

    start_s: float
    end_s: float
    text: str
    confidence: float
    words: tuple[WordResult, ...] = ()
    speaker: int | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    """Wynik ASR: hipoteza ortograficzna i segmenty z przedziałami pewności."""

    text: str
    language: str
    segments: tuple[SegmentResult, ...] = field(default_factory=tuple)
    device: str = "cpu"
    # Przyczyna przejścia z GPU na CPU (None, gdy nie było próby GPU
    # albo się udała).
    device_note: str | None = None
    # Przyczyna braku podziału na mówców, gdy diaryzacja zawiodła.
    diarization_note: str | None = None

    @property
    def diarized(self) -> bool:
        """Czy segmenty mają mówców (wynik diaryzacji)."""
        return any(segment.speaker is not None for segment in self.segments)


def draft_text(
    result: TranscriptionResult, line_seconds: float = DRAFT_LINE_SECONDS
) -> str:
    """Szkic do edytora: wersy ze znacznikiem czasu ``[mm:ss]`` na początku.

    Wynik z mówcami (diaryzacja) ma wers na każdą wypowiedź: nowy wers
    zaczyna się przy zmianie mówcy. Bez mówców segmenty są łączone w wersy
    obejmujące najwyżej ``line_seconds`` nagrania (dłuższy pojedynczy
    segment tworzy własny wers), więc tekst - także w eksporcie DOCX - ma
    podział co najwyżej co tyle sekund. Wynik bez segmentów (np. ze
    starszego projektu) zwraca samą hipotezę.
    """
    lines = _draft_lines(result, line_seconds)
    return "\n".join(text for text, _speaker in lines) if lines else result.text


def draft_line_speakers(
    result: TranscriptionResult, line_seconds: float = DRAFT_LINE_SECONDS
) -> list[int | None]:
    """Mówca każdego wersu ``draft_text`` (puste, gdy szkic nie ma wersów)."""
    return [speaker for _text, speaker in _draft_lines(result, line_seconds)]


def _draft_lines(
    result: TranscriptionResult, line_seconds: float
) -> list[tuple[str, int | None]]:
    by_speaker = result.diarized
    lines: list[tuple[str, int | None]] = []
    words: list[str] = []
    line_start = 0.0
    speaker: int | None = None
    for segment in result.segments:
        text = segment.text.strip()
        if not text:
            continue
        if by_speaker:
            new_line = segment.speaker != speaker
        else:
            new_line = segment.end_s - line_start > line_seconds
        if not words or new_line:
            if words:
                lines.append((" ".join(words), speaker))
            line_start = segment.start_s
            speaker = segment.speaker
            words = [f"[{format_timestamp(line_start)}]"]
        words.append(text)
    if words:
        lines.append((" ".join(words), speaker))
    return lines


def format_timestamp(seconds: float) -> str:
    """Czas jako ``mm:ss``, a od godziny nagrania - ``h:mm:ss``."""
    minutes, secs = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def words_of(raw: Any, offset: float = 0.0) -> tuple[WordResult, ...]:
    """Słowa segmentu backendu (puste, gdy nie liczono ich czasów)."""
    return tuple(
        WordResult(
            start_s=float(word.start) + offset,
            end_s=float(word.end) + offset,
            text=str(word.word),
            probability=round(float(word.probability), 3),
        )
        for word in getattr(raw, "words", None) or ()
    )


def confidence_of(avg_logprob: float) -> float:
    """Przybliżona pewność segmentu z logarytmu prawdopodobieństwa."""
    return round(min(1.0, max(0.0, math.exp(avg_logprob))), 3)


__all__ = [
    "DRAFT_LINE_SECONDS",
    "SegmentResult",
    "TranscriptionResult",
    "WordResult",
    "confidence_of",
    "draft_line_speakers",
    "draft_text",
    "format_timestamp",
    "words_of",
]
