"""Transkrypcja fragmentami: nagranie dekodowane raz, model dostaje kolejne
kilkuminutowe fragmenty cięte w ciszy - szczyt pamięci cech nie zależy od
długości nagrania (``DecodingOptions.chunked`` i ``clip``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from transkryptor.asr import backend
from transkryptor.asr.backend import SAMPLE_RATE
from transkryptor.asr.results import words_of

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

# Długość fragmentu przy transkrypcji fragmentami. Szczyt pamięci cech dla
# 5 minut to ok. 0,3 GB; dłuższe fragmenty nie poprawiają jakości (Whisper
# i tak pracuje w oknach 30 s), a krótsze mnożą cięcia.
CHUNK_S = 300.0
# Okno przed nominalnym końcem fragmentu, w którym szukamy najcichszego
# miejsca na cięcie, żeby nie przecinać słów.
CUT_SEARCH_S = 20.0
CUT_FRAME_S = 0.1


def chunk_bounds(
    samples: npt.NDArray[np.float32],
    *,
    sample_rate: int = SAMPLE_RATE,
    chunk_s: float = CHUNK_S,
    search_s: float = CUT_SEARCH_S,
) -> list[tuple[int, int]]:
    """Dzieli nagranie na przylegające fragmenty ``[start, end)`` w próbkach.

    Każdy fragment ma najwyżej ``chunk_s`` sekund. Cięcie wypada w najcichszej
    ramce (najniższa energia RMS) w ostatnich ``search_s`` sekundach przed
    nominalnym końcem fragmentu, żeby nie przecinać słów.
    """
    import numpy as np

    total = len(samples)
    chunk = int(chunk_s * sample_rate)
    search = min(int(search_s * sample_rate), chunk // 2)
    frame = max(1, int(CUT_FRAME_S * sample_rate))
    bounds: list[tuple[int, int]] = []
    start = 0
    while total - start > chunk:
        window_start = start + chunk - search
        window = samples[window_start : start + chunk]
        frames = len(window) // frame
        energy = np.square(window[: frames * frame].reshape(frames, frame)).mean(axis=1)
        # Tniemy w środku najcichszej ramki.
        cut = window_start + int(np.argmin(energy)) * frame + frame // 2
        bounds.append((start, cut))
        start = cut
    if start < total or not bounds:
        bounds.append((start, total))
    return bounds


@dataclass(frozen=True)
class _ShiftedWord:
    start: float
    end: float
    word: str
    probability: float


@dataclass(frozen=True)
class _ShiftedSegment:
    start: float
    end: float
    text: str
    avg_logprob: float
    words: tuple[_ShiftedWord, ...] = ()


@dataclass(frozen=True)
class ChunkDone:
    """Znacznik końca fragmentu w strumieniu segmentów (sekundy nagrania)."""

    end: float


class ChunkedWhisperBackend:
    """Backend zgodny z :class:`Backend`, transkrybujący nagranie fragmentami.

    Nagranie jest dekodowane raz (ok. 0,25 GB na godzinę), a model dostaje
    kolejne fragmenty jako tablice próbek; czasy segmentów są przesuwane
    o początek fragmentu. ``clip`` (sekundy od-do) ogranicza pracę do
    jednego zakresu nagrania. Po każdym fragmencie strumień zawiera znacznik
    ``ChunkDone`` - :func:`transcribe` liczy z niego postęp także wtedy,
    gdy fragment nie zawiera mowy.
    """

    def __init__(
        self,
        model: Any,
        *,
        decode: Callable[[str], npt.NDArray[np.float32]] | None = None,
        chunk_s: float = CHUNK_S,
        clip: tuple[float, float] | None = None,
    ) -> None:
        self._model = model
        self._decode = decode or backend.decode_audio
        self._chunk_s = chunk_s
        self._clip = clip

    def transcribe(
        self, audio: str, /, *, language: str, vad_filter: bool, **extra: Any
    ) -> tuple[Iterable[Any], Any]:
        samples = self._decode(audio)
        info = SimpleNamespace(language=language, duration=len(samples) / SAMPLE_RATE)
        first, last = 0, len(samples)
        if self._clip is not None:
            first = min(last, max(0, int(self._clip[0] * SAMPLE_RATE)))
            last = min(last, max(first, int(self._clip[1] * SAMPLE_RATE)))
        bounds = [
            (start + first, end + first)
            for start, end in chunk_bounds(samples[first:last], chunk_s=self._chunk_s)
        ]
        segments = self._segments(samples, bounds, language, vad_filter, extra)
        return segments, info

    def _segments(
        self,
        samples: npt.NDArray[np.float32],
        bounds: list[tuple[int, int]],
        language: str,
        vad_filter: bool,
        extra: dict[str, Any],
    ) -> Iterator[_ShiftedSegment | ChunkDone]:
        for start, end in bounds:
            offset = start / SAMPLE_RATE
            raw_segments, _info = self._model.transcribe(
                samples[start:end], language=language, vad_filter=vad_filter, **extra
            )
            for raw in raw_segments:
                yield _ShiftedSegment(
                    start=float(raw.start) + offset,
                    end=float(raw.end) + offset,
                    text=raw.text,
                    avg_logprob=float(raw.avg_logprob),
                    words=tuple(
                        _ShiftedWord(w.start_s, w.end_s, w.text, w.probability)
                        for w in words_of(raw, offset)
                    ),
                )
            yield ChunkDone(end / SAMPLE_RATE)


__all__ = ["CHUNK_S", "ChunkDone", "ChunkedWhisperBackend", "chunk_bounds"]
