"""Podział szkicu ASR na mówców (diaryzacja) — lokalnie, przez sherpa-onnx.

Granica modułu: brak zależności od GUI ani Qt. Diaryzacja działa na
próbkach całego nagrania (16 kHz, mono) po transkrypcji Whispera:

1. model segmentacji (pyannote/segmentation-3.0) wyznacza fragmenty mowy
   i zmiany mówcy, a model głosu (3D-Speaker CAM++) grupuje je po głosie —
   wynikiem są wypowiedzi (:class:`Turn`) z numerem mówcy;
2. :func:`assign_speakers` przypisuje mówcę każdemu słowu Whispera
   (największe nakładanie czasu) i dzieli segment w miejscu zmiany mówcy.

Liczba mówców jest wyznaczana automatycznie (próg grupowania). Numery
mówców w wyniku idą w kolejności pojawiania się w tekście, od 0.
"""

from __future__ import annotations

import bisect
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from transkryptor.asr.models import (
    DIARIZATION_EMBEDDING_FILE,
    DIARIZATION_SEGMENTATION_FILE,
)

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from transkryptor.asr.engine import SegmentResult, WordResult

# Próg odległości przy grupowaniu wypowiedzi po głosie (wartość domyślna
# sherpa-onnx): wyższy łączy więcej wypowiedzi w jednego mówcę.
CLUSTER_THRESHOLD = 0.5
# Najkrótszy fragment mowy i najkrótsza przerwa w wypowiedzi (sekundy).
MIN_DURATION_ON_S = 0.3
MIN_DURATION_OFF_S = 0.5
MAX_THREADS = 4

DiarizationProgress = Callable[[float], None]  # ułamek pracy 0.0–1.0


class DiarizationCancelled(Exception):
    """Diaryzacja przerwana na życzenie użytkownika."""


@dataclass(frozen=True)
class Turn:
    """Wypowiedź jednego mówcy w nagraniu (sekundy)."""

    start_s: float
    end_s: float
    speaker: int


class Diarizer(Protocol):
    """Kontrakt ``sherpa_onnx.OfflineSpeakerDiarization``."""

    def process(
        self, samples: Any, callback: Callable[[int, int], int] | None = None
    ) -> Any: ...


# Wstrzykiwalna fabryka (katalog modelu → diaryzator); testy podstawiają
# imitację bez modelu.
DiarizerFactory = Callable[[Path], Diarizer]


def sherpa_diarizer(model_dir: Path) -> Diarizer:
    """Diaryzator sherpa-onnx z plików pobranego modelu (offline, CPU)."""
    import sherpa_onnx

    for name in (DIARIZATION_SEGMENTATION_FILE, DIARIZATION_EMBEDDING_FILE):
        if not (model_dir / name).is_file():
            raise FileNotFoundError(f"missing diarization model file: {name}")
    threads = max(1, min(MAX_THREADS, (os.cpu_count() or 2) // 2))
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(model_dir / DIARIZATION_SEGMENTATION_FILE)
            ),
            num_threads=threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_dir / DIARIZATION_EMBEDDING_FILE),
            num_threads=threads,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=-1, threshold=CLUSTER_THRESHOLD
        ),
        min_duration_on=MIN_DURATION_ON_S,
        min_duration_off=MIN_DURATION_OFF_S,
    )
    if not config.validate():
        raise ValueError("invalid diarization model configuration")
    diarizer: Diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    return diarizer


def diarize(
    samples: npt.NDArray[np.float32],
    model_dir: Path,
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    on_progress: DiarizationProgress | None = None,
    factory: DiarizerFactory | None = None,
) -> tuple[Turn, ...]:
    """Wypowiedzi mówców w nagraniu, posortowane po czasie początku.

    Podnosi :class:`DiarizationCancelled` przy anulowaniu; pozostałe błędy
    (brak pliku modelu, błąd biblioteki) przechodzą bez zmian.
    """
    diarizer = (factory or sherpa_diarizer)(model_dir)

    def callback(done: int, total: int) -> int:
        if on_progress is not None and total > 0:
            on_progress(min(1.0, done / total))
        return 1 if should_cancel() else 0

    result = diarizer.process(samples, callback=callback)
    if should_cancel():
        raise DiarizationCancelled()
    turns = [
        Turn(float(item.start), float(item.end), int(item.speaker))
        for item in result.sort_by_start_time()
        if float(item.end) > float(item.start)
    ]
    return tuple(sorted(turns, key=lambda turn: (turn.start_s, turn.end_s)))


class _TurnIndex:
    """Wyszukiwanie mówcy przedziału czasu bez przeglądania wszystkich wypowiedzi."""

    def __init__(self, turns: Sequence[Turn]) -> None:
        self._turns = sorted(turns, key=lambda turn: turn.start_s)
        self._starts = [turn.start_s for turn in self._turns]
        self._longest = max(
            (turn.end_s - turn.start_s for turn in self._turns), default=0.0
        )

    def speaker(self, start_s: float, end_s: float) -> int | None:
        """Mówca o największym nakładaniu z ``[start_s, end_s]``.

        Bez nakładania — mówca najbliższej wypowiedzi; None, gdy nie ma
        żadnej wypowiedzi.
        """
        if not self._turns:
            return None
        overlaps: dict[int, float] = {}
        index = bisect.bisect_right(self._starts, end_s) - 1
        # Wypowiedź zaczynająca się wcześniej niż start - najdłuższa
        # wypowiedź nie może już sięgać przedziału.
        while index >= 0 and self._starts[index] >= start_s - self._longest:
            turn = self._turns[index]
            overlap = min(end_s, turn.end_s) - max(start_s, turn.start_s)
            if overlap > 0:
                overlaps[turn.speaker] = overlaps.get(turn.speaker, 0.0) + overlap
            index -= 1
        if overlaps:
            return max(overlaps, key=lambda speaker: overlaps[speaker])
        middle = (start_s + end_s) / 2
        nearest = min(
            self._nearby(middle),
            key=lambda turn: max(turn.start_s - middle, middle - turn.end_s, 0.0),
        )
        return nearest.speaker

    def _nearby(self, moment: float) -> list[Turn]:
        index = bisect.bisect_right(self._starts, moment)
        candidates = self._turns[max(0, index - 1) : index + 1]
        # Wcześniejsza wypowiedź może kończyć się później niż poprzednia.
        lookback = index - 2
        while lookback >= 0 and self._starts[lookback] >= moment - self._longest:
            candidates.append(self._turns[lookback])
            lookback -= 1
        return candidates


def assign_speakers(
    segments: Iterable[SegmentResult], turns: Sequence[Turn]
) -> tuple[SegmentResult, ...]:
    """Segmenty z mówcami; segment ze zmianą mówcy jest dzielony na słowach.

    Słowo dostaje mówcę o największym nakładaniu czasu, a segment bez słów —
    mówcę całego segmentu. Pojedyncze słowo innego mówcy w środku segmentu
    (szum na granicy wypowiedzi) nie dzieli segmentu. Numery mówców są
    nadawane od nowa w kolejności pojawiania się.
    """
    index = _TurnIndex(turns)
    assigned: list[SegmentResult] = []
    for segment in segments:
        if not segment.words:
            speaker = index.speaker(segment.start_s, segment.end_s)
            assigned.append(replace(segment, speaker=speaker))
            continue
        speakers = [index.speaker(word.start_s, word.end_s) for word in segment.words]
        groups = _groups(segment.words, _smoothed(speakers))
        for position, (words, speaker) in enumerate(groups):
            # Pierwsza i ostatnia część zachowują granice segmentu.
            assigned.append(
                replace(
                    segment,
                    start_s=segment.start_s if position == 0 else words[0].start_s,
                    end_s=(
                        segment.end_s
                        if position == len(groups) - 1
                        else words[-1].end_s
                    ),
                    text="".join(word.text for word in words),
                    words=tuple(words),
                    speaker=speaker,
                )
            )
    return _renumbered(assigned)


def _smoothed(speakers: list[int | None]) -> list[int | None]:
    """Pojedyncze słowo otoczone słowami jednego mówcy dostaje jego numer."""
    result = list(speakers)
    for position in range(1, len(result) - 1):
        before, after = result[position - 1], result[position + 1]
        if before == after and result[position] != before:
            result[position] = before
    return result


def _groups(
    words: Sequence[WordResult], speakers: Sequence[int | None]
) -> list[tuple[list[WordResult], int | None]]:
    groups: list[tuple[list[WordResult], int | None]] = []
    for word, speaker in zip(words, speakers, strict=True):
        if groups and groups[-1][1] == speaker:
            groups[-1][0].append(word)
        else:
            groups.append(([word], speaker))
    return groups


def _renumbered(segments: list[SegmentResult]) -> tuple[SegmentResult, ...]:
    numbers: dict[int, int] = {}
    result: list[SegmentResult] = []
    for segment in segments:
        speaker = segment.speaker
        if speaker is not None:
            speaker = numbers.setdefault(speaker, len(numbers))
        result.append(replace(segment, speaker=speaker))
    return tuple(result)


__all__ = [
    "DiarizationCancelled",
    "Diarizer",
    "DiarizerFactory",
    "Turn",
    "assign_speakers",
    "diarize",
    "sherpa_diarizer",
]
