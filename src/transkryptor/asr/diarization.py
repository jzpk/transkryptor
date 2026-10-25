"""Podział szkicu ASR na mówców (diaryzacja) - lokalnie, przez sherpa-onnx.

Granica modułu: brak zależności od GUI ani Qt. Diaryzacja działa na
próbkach całego nagrania (16 kHz, mono) po transkrypcji Whispera:

1. :func:`diarize` liczy model głosu (3D-Speaker CAM++) dla krótkich okien
   przesuwanych po fragmentach mowy wskazanych przez słowa Whispera
   i grupuje okna po głosie (grupowanie spektralne) - wynikiem są
   wypowiedzi (:class:`Turn`) z numerem mówcy;
2. :func:`assign_speakers` przypisuje mówcę każdemu słowu Whispera
   (największe nakładanie czasu) i dzieli segment w miejscu zmiany mówcy.

Krótkie okna wychwytują szybkie wymiany pytań i odpowiedzi w wywiadach
(„Zajęcie?” - „Rolnik.”), które gubi segmentacja pyannote działająca na
oknach 10-sekundowych. Liczba mówców jest podana przez użytkownika albo
wyznaczana automatycznie (największa przerwa w widmie grafu podobieństwa).
Numery mówców w wyniku idą w kolejności pojawiania się w tekście, od 0.
"""

from __future__ import annotations

import bisect
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from transkryptor.asr.models import DIARIZATION_EMBEDDING_FILE

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    from transkryptor.asr.engine import SegmentResult, WordResult

SAMPLE_RATE = 16_000
MAX_SPEAKERS = 8
# Okno modelu głosu i krok, co który okno jest przesuwane (sekundy):
# krótsze okno szybciej reaguje na zmianę mówcy, ale niesie mniej głosu.
WINDOW_S = 1.5
STEP_S = 0.25
# Grupowanie spektralne liczy macierz podobieństwa wszystkich par okien,
# więc w długim nagraniu działa na równomiernej próbce okien; pozostałe
# dostają mówcę najbliższego środka grupy.
MAX_CLUSTERED_WINDOWS = 1500
# Część najbardziej podobnych okien zachowywana w grafie dla każdego okna
# (odcina przypadkowe podobieństwa między różnymi głosami).
NEIGHBOUR_SHARE = 0.1
REFINE_ROUNDS = 5
KMEANS_ROUNDS = 30
MAX_THREADS = 4
# Co tyle okien raportowany jest postęp i sprawdzane anulowanie.
PROGRESS_EVERY = 20
# Znaki kończące zdanie w tekście Whispera (granice wypowiedzi).
SENTENCE_END = (".", "?", "!", "…")

DiarizationProgress = Callable[[float], None]  # ułamek pracy 0.0-1.0
Span = tuple[float, float]  # przedział czasu w sekundach


class DiarizationCancelled(Exception):
    """Diaryzacja przerwana na życzenie użytkownika."""


@dataclass(frozen=True)
class Turn:
    """Wypowiedź jednego mówcy w nagraniu (sekundy)."""

    start_s: float
    end_s: float
    speaker: int


class Embedder(Protocol):
    """Model głosu: wektor cech mówcy dla fragmentu próbek (16 kHz)."""

    def embed(self, samples: npt.NDArray[np.float32]) -> Sequence[float]: ...


# Wstrzykiwalna fabryka (katalog modelu → model głosu); testy podstawiają
# imitację bez modelu.
EmbedderFactory = Callable[[Path], Embedder]


class _SherpaEmbedder:
    def __init__(self, extractor: Any) -> None:
        self._extractor = extractor

    def embed(self, samples: npt.NDArray[np.float32]) -> Sequence[float]:
        stream = self._extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        stream.input_finished()
        embedding: Sequence[float] = self._extractor.compute(stream)
        return embedding


def sherpa_embedder(model_dir: Path) -> Embedder:
    """Model głosu sherpa-onnx z pliku pobranego modelu (offline, CPU)."""
    import sherpa_onnx

    model = model_dir / DIARIZATION_EMBEDDING_FILE
    if not model.is_file():
        raise FileNotFoundError(
            f"missing diarization model file: {DIARIZATION_EMBEDDING_FILE}"
        )
    threads = max(1, min(MAX_THREADS, (os.cpu_count() or 2) // 2))
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(model), num_threads=threads
    )
    if not config.validate():
        raise ValueError("invalid diarization model configuration")
    return _SherpaEmbedder(sherpa_onnx.SpeakerEmbeddingExtractor(config))


def diarize(
    samples: npt.NDArray[np.float32],
    model_dir: Path,
    speech: Iterable[Span],
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    on_progress: DiarizationProgress | None = None,
    speakers: int | None = None,
    factory: EmbedderFactory | None = None,
) -> tuple[Turn, ...]:
    """Wypowiedzi mówców w nagraniu, posortowane po czasie początku.

    ``speech`` - fragmenty mowy (np. słowa Whispera); tylko one są dzielone
    na mówców. ``speakers`` - znana liczba mówców (None: wyznaczana
    automatycznie). Podnosi :class:`DiarizationCancelled` przy anulowaniu;
    pozostałe błędy (brak pliku modelu, błąd biblioteki) przechodzą bez zmian.
    """
    import numpy as np

    embedder = (factory or sherpa_embedder)(model_dir)
    centres = _window_centres(speech)
    window = int(WINDOW_S * SAMPLE_RATE)
    vectors: list[npt.NDArray[np.float64]] = []
    for position, centre in enumerate(centres):
        if position % PROGRESS_EVERY == 0:
            if should_cancel():
                raise DiarizationCancelled()
            if on_progress is not None:
                on_progress(position / len(centres))
        start = max(
            0, min(int((centre - WINDOW_S / 2) * SAMPLE_RATE), len(samples) - window)
        )
        vector = np.asarray(
            embedder.embed(samples[start : start + window]), dtype=np.float64
        )
        vectors.append(vector / max(float(np.linalg.norm(vector)), 1e-9))
    if should_cancel():
        raise DiarizationCancelled()
    if on_progress is not None:
        on_progress(1.0)
    if not vectors:
        return ()
    labels = _cluster(np.array(vectors), speakers)
    return _turns(centres, labels)


def _window_centres(speech: Iterable[Span]) -> list[float]:
    """Środki okien na siatce co ``STEP_S`` wewnątrz fragmentów mowy."""
    steps: set[int] = set()
    for start_s, end_s in speech:
        first = int(-(-start_s // STEP_S))  # zaokrąglenie w górę
        last = int(end_s // STEP_S)
        if first > last:
            # Fragment krótszy niż krok też dostaje okno (krótka odpowiedź).
            steps.add(round((start_s + end_s) / 2 / STEP_S))
        steps.update(range(first, last + 1))
    return [step * STEP_S for step in sorted(steps)]


def _cluster(vectors: npt.NDArray[np.float64], speakers: int | None) -> list[int]:
    """Numer grupy (mówcy) każdego okna; wektory są znormalizowane."""
    import numpy as np

    count = len(vectors)
    sample = np.unique(
        np.linspace(0, count - 1, min(count, MAX_CLUSTERED_WINDOWS)).astype(int)
    )
    sample_labels = _spectral(vectors[sample], speakers)
    groups = int(sample_labels.max()) + 1
    centroids = np.array(
        [
            vectors[sample][sample_labels == group].mean(axis=0)
            for group in range(groups)
        ]
    )
    labels = sample_labels
    for _ in range(REFINE_ROUNDS):
        centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-9)
        labels = np.argmax(vectors @ centroids.T, axis=1)
        centroids = np.array(
            [
                (
                    vectors[labels == group].mean(axis=0)
                    if (labels == group).any()
                    else centroids[group]
                )
                for group in range(groups)
            ]
        )
    return [int(label) for label in labels]


def _spectral(
    vectors: npt.NDArray[np.float64], speakers: int | None
) -> npt.NDArray[np.int_]:
    """Grupowanie spektralne okien na ``speakers`` grup (None: z widma)."""
    import numpy as np

    count = len(vectors)
    if count < 2:
        return np.zeros(count, dtype=int)
    affinity = vectors @ vectors.T
    keep = min(count, max(2, round(count * NEIGHBOUR_SHARE)))
    threshold = np.sort(affinity, axis=1)[:, -keep][:, None]
    affinity = np.where(affinity >= threshold, affinity, 0.0)
    affinity = np.clip(np.maximum(affinity, affinity.T), 0.0, None)
    degree = np.maximum(affinity.sum(axis=1), 1e-9)
    laplacian = np.eye(count) - affinity / np.sqrt(np.outer(degree, degree))
    values, eigenvectors = np.linalg.eigh(laplacian)
    limit = min(MAX_SPEAKERS, count - 1)
    if speakers is None:
        groups = int(np.argmax(np.diff(values[: limit + 1]))) + 1
    else:
        groups = max(1, min(speakers, count))
    points = eigenvectors[:, :groups]
    points = points / np.maximum(np.linalg.norm(points, axis=1, keepdims=True), 1e-9)
    # Deterministyczny start k-średnich: kolejno punkt najdalszy od wybranych.
    chosen = [0]
    for _ in range(1, groups):
        chosen.append(int(np.argmin(np.max(points @ points[chosen].T, axis=1))))
    centres = points[chosen]
    labels = np.zeros(count, dtype=int)
    for _ in range(KMEANS_ROUNDS):
        labels = np.argmax(points @ centres.T, axis=1)
        centres = np.array(
            [
                (
                    points[labels == group].mean(axis=0)
                    if (labels == group).any()
                    else centres[group]
                )
                for group in range(groups)
            ]
        )
    # Numery bez luk: grupa bez okien nie tworzy mówcy.
    _, compact = np.unique(labels, return_inverse=True)
    return compact.astype(int)


def _turns(centres: Sequence[float], labels: Sequence[int]) -> tuple[Turn, ...]:
    """Sąsiednie okna jednego mówcy łączone w wypowiedzi."""
    turns: list[Turn] = []
    for centre, speaker in zip(centres, labels, strict=True):
        start_s, end_s = max(0.0, centre - STEP_S / 2), centre + STEP_S / 2
        last = turns[-1] if turns else None
        if last is not None and last.speaker == speaker and start_s - last.end_s < 1e-6:
            turns[-1] = replace(last, end_s=end_s)
        else:
            turns.append(Turn(start_s, end_s, speaker))
    return tuple(turns)


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

        Bez nakładania - mówca najbliższej wypowiedzi; None, gdy nie ma
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

    Słowo dostaje mówcę o największym nakładaniu czasu, a segment bez słów -
    mówcę całego segmentu. Zmiana mówcy o jedno słowo od końca zdania jest
    przesuwana na koniec zdania (:func:`_snapped`). Numery mówców są
    nadawane od nowa w kolejności pojawiania się.
    """
    index = _TurnIndex(turns)
    segments = list(segments)
    words = [word for segment in segments for word in segment.words]
    speakers = iter(
        _snapped(words, [index.speaker(word.start_s, word.end_s) for word in words])
    )
    assigned: list[SegmentResult] = []
    for segment in segments:
        if not segment.words:
            speaker = index.speaker(segment.start_s, segment.end_s)
            assigned.append(replace(segment, speaker=speaker))
            continue
        groups = _groups(segment.words, [next(speakers) for _ in segment.words])
        for position, (group, speaker) in enumerate(groups):
            # Pierwsza i ostatnia część zachowują granice segmentu.
            assigned.append(
                replace(
                    segment,
                    start_s=segment.start_s if position == 0 else group[0].start_s,
                    end_s=(
                        segment.end_s
                        if position == len(groups) - 1
                        else group[-1].end_s
                    ),
                    text="".join(word.text for word in group),
                    words=tuple(group),
                    speaker=speaker,
                )
            )
    return _renumbered(assigned)


def _ends_sentence(word: WordResult) -> bool:
    return word.text.rstrip().endswith(SENTENCE_END)


def _snapped(
    words: Sequence[WordResult], speakers: list[int | None]
) -> list[int | None]:
    """Zmiany mówcy przesunięte o jedno słowo na koniec zdania.

    Okno modelu głosu rozmywa moment zmiany, więc granica wypada często
    słowo przed albo po końcu zdania („starsze, | młodsze? To…”). Granicy
    zaraz po końcu zdania się nie rusza; słowo nie zmienia mówcy, gdy
    stanowiłoby wtedy całą wypowiedź (krótka odpowiedź „Tak.” zostaje).
    """
    result = list(speakers)
    for position in range(1, len(words)):
        before, after = result[position - 1], result[position]
        if before == after or _ends_sentence(words[position - 1]):
            continue
        following = result[position + 1] if position + 1 < len(words) else None
        preceding = result[position - 2] if position >= 2 else None
        if _ends_sentence(words[position]) and following == after:
            # Słowo kończące zdanie poprzedniego mówcy: granica o słowo dalej.
            result[position] = before
        elif (
            position >= 2
            and _ends_sentence(words[position - 2])
            and preceding == before
        ):
            # Pierwsze słowo nowego zdania: granica o słowo wcześniej.
            result[position - 1] = after
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
    "Embedder",
    "EmbedderFactory",
    "MAX_SPEAKERS",
    "Turn",
    "assign_speakers",
    "diarize",
    "sherpa_embedder",
]
