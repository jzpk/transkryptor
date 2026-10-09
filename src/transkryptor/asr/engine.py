"""Silnik transkrypcji ASR: lokalne wykonanie, anulowanie, wynik z pewnością.

Granica modułu: brak zależności od GUI ani Qt. Wykonanie jest synchroniczne
i kooperacyjnie anulowane między segmentami — wątek tła dostarcza warstwa UI.

Model jest ładowany wyłącznie z lokalnego katalogu (``local_files_only``),
więc po pobraniu transkrypcja nie generuje ruchu sieciowego (ACC-11).
Dekodowanie audio (MP3, WAV, FLAC, AAC itd.) realizuje faster-whisper przez PyAV/FFmpeg.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from transkryptor.asr.models import DEFAULT_MODEL, AsrModelInfo
from transkryptor.errors import AppError, ModelDownloadError
from transkryptor.i18n import tr

LANGUAGE = "pl"


class TranscriptionCancelled(Exception):
    """Transkrypcja przerwana na życzenie użytkownika (nie jest błędem)."""


class TranscriptionError(AppError):
    """Nie udało się wykonać lokalnej transkrypcji."""


@dataclass(frozen=True)
class SegmentResult:
    """Fragment hipotezy z czasem i przybliżoną pewnością (0.0–1.0)."""

    start_s: float
    end_s: float
    text: str
    confidence: float


@dataclass(frozen=True)
class TranscriptionResult:
    """Wynik ASR: hipoteza ortograficzna i segmenty z przedziałami pewności."""

    text: str
    language: str
    segments: tuple[SegmentResult, ...] = field(default_factory=tuple)


CancelCheck = Callable[[], bool]
SegmentCallback = Callable[[SegmentResult], None]
ProgressCallback = Callable[[float], None]  # ułamek nagrania 0.0–1.0


class Backend(Protocol):
    """Kontrakt backendu zgodny z ``faster_whisper.WhisperModel.transcribe``.

    Zwraca parę (iterowalne_segmenty, info); segmenty mają ``start``,
    ``end``, ``text`` i ``avg_logprob``, a info opcjonalnie ``language``
    i ``duration``.
    """

    def transcribe(
        self, audio: str, /, *, language: str, vad_filter: bool
    ) -> tuple[Iterable[Any], Any]: ...


# Wstrzykiwalna fabryka backendu (testy podstawiają imitację bez modelu).
BackendFactory = Callable[[Path], Backend]


def transcribe(
    audio_path: str | Path,
    model_dir: str | Path,
    *,
    model: AsrModelInfo = DEFAULT_MODEL,
    should_cancel: CancelCheck | None = None,
    on_segment: SegmentCallback | None = None,
    on_progress: ProgressCallback | None = None,
    backend_factory: BackendFactory | None = None,
    language: str = LANGUAGE,
) -> TranscriptionResult:
    """Wykonuje lokalną transkrypcję pliku audio.

    Podnosi :class:`ModelDownloadError`, gdy model nie jest kompletny,
    :class:`TranscriptionCancelled` przy anulowaniu oraz
    :class:`TranscriptionError` przy błędzie wykonania.

    ``on_progress`` dostaje po każdym segmencie ułamek przetworzonego
    nagrania (koniec segmentu względem długości audio); nie jest wołane,
    gdy backend nie zna długości nagrania.
    """
    cancel = should_cancel or (lambda: False)
    audio = Path(audio_path)
    if not audio.is_file():
        raise TranscriptionError(
            user_message=tr("asr.error.audio_missing", name=audio.name),
            retry_hint=tr("asr.error.audio_missing.hint"),
        )
    model_path = Path(model_dir)
    if not (model_path / ".complete").is_file():
        raise ModelDownloadError(
            user_message=tr("asr.error.not_downloaded", model=model.display_name),
            retry_hint=tr("asr.error.not_downloaded.hint"),
        )
    if cancel():
        raise TranscriptionCancelled()
    factory = backend_factory or _faster_whisper_backend
    try:
        backend = factory(model_path)
        raw_segments, info = backend.transcribe(
            str(audio),
            language=language,
            vad_filter=True,
        )
    except (ModelDownloadError, TranscriptionCancelled):
        raise
    except Exception as error:  # noqa: BLE001 — normalizacja do AppError
        raise TranscriptionError(
            user_message=tr("asr.error.transcribe", reason=error),
            retry_hint=tr("asr.error.transcribe.hint"),
        ) from error
    duration = float(getattr(info, "duration", 0) or 0)
    progress = 0.0
    segments: list[SegmentResult] = []
    for raw in raw_segments:
        if cancel():
            raise TranscriptionCancelled()
        segment = SegmentResult(
            start_s=float(raw.start),
            end_s=float(raw.end),
            text=raw.text,
            confidence=_confidence(raw.avg_logprob),
        )
        segments.append(segment)
        if on_segment is not None:
            on_segment(segment)
        if on_progress is not None and duration > 0:
            # Segmenty idą chronologicznie, ale max() chroni przed cofaniem.
            progress = max(progress, min(1.0, segment.end_s / duration))
            on_progress(progress)
    if cancel():
        raise TranscriptionCancelled()
    return TranscriptionResult(
        text="".join(segment.text for segment in segments).strip(),
        language=getattr(info, "language", language),
        segments=tuple(segments),
    )


def _confidence(avg_logprob: float) -> float:
    """Przybliżona pewność segmentu z logarytmu prawdopodobieństwa."""
    return round(min(1.0, max(0.0, math.exp(avg_logprob))), 3)


def _faster_whisper_backend(model_dir: Path) -> Backend:
    """Ładuje model faster-whisper wyłącznie z lokalnych plików (offline)."""
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_dir),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )


__all__ = [
    "Backend",
    "SegmentResult",
    "TranscriptionCancelled",
    "TranscriptionError",
    "TranscriptionResult",
    "transcribe",
]
