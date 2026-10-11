"""Silnik transkrypcji ASR: lokalne wykonanie, anulowanie, wynik z pewnością.

Granica modułu: brak zależności od GUI ani Qt. Wykonanie jest synchroniczne
i kooperacyjnie anulowane między segmentami — wątek tła dostarcza warstwa UI.

Model jest ładowany wyłącznie z lokalnego katalogu (``local_files_only``),
więc po pobraniu transkrypcja nie generuje ruchu sieciowego (ACC-11).
Dekodowanie audio (MP3, WAV, FLAC, AAC itd.) realizuje faster-whisper przez PyAV/FFmpeg.

Urządzenie ``auto`` używa karty CUDA, gdy CTranslate2 ją widzi; błąd
ładowania modelu lub pierwszego dekodowania na GPU (np. brak bibliotek
cuBLAS/cuDNN) powoduje ponowienie na CPU z informacją w wyniku (ACC-37).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from transkryptor.asr.models import DEFAULT_MODEL, AsrModelInfo
from transkryptor.asr.system import cuda_device_count
from transkryptor.errors import AppError, ModelDownloadError
from transkryptor.i18n import tr

LANGUAGE = "pl"

DEVICES = ("auto", "cpu")
# Limit podpowiedzi kontekstowej i słownika: okno promptu Whispera to
# 224 tokeny, a długi prompt sprzyja halucynacjom (powtarzaniu promptu).
PROMPT_MAX_CHARS = 200
_DEVICE_NOTE_MAX_CHARS = 200


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
    device: str = "cpu"
    # Przyczyna przejścia z GPU na CPU (None, gdy nie było próby GPU
    # albo się udała).
    device_note: str | None = None


@dataclass(frozen=True)
class DecodingOptions:
    """Parametry transkrypcji wybrane przez użytkownika (REQ-10, REQ-21).

    ``initial_prompt`` i ``hotwords`` trafiają do Whispera tylko, gdy nie są
    puste — bez nich zachowanie jest takie jak przed fazą 09.
    """

    device: str = "auto"
    initial_prompt: str | None = None
    hotwords: str | None = None


CancelCheck = Callable[[], bool]
SegmentCallback = Callable[[SegmentResult], None]
ProgressCallback = Callable[[float], None]  # ułamek nagrania 0.0–1.0


class Backend(Protocol):
    """Kontrakt backendu zgodny z ``faster_whisper.WhisperModel.transcribe``.

    Zwraca parę (iterowalne_segmenty, info); segmenty mają ``start``,
    ``end``, ``text`` i ``avg_logprob``, a info opcjonalnie ``language``
    i ``duration``. Niepuste ``initial_prompt`` i ``hotwords`` są
    przekazywane dodatkowo jako argumenty nazwane.
    """

    def transcribe(
        self, audio: str, /, *, language: str, vad_filter: bool
    ) -> tuple[Iterable[Any], Any]: ...


# Wstrzykiwalna fabryka backendu: (katalog modelu, urządzenie "cuda"/"cpu").
# Testy podstawiają imitację bez modelu.
BackendFactory = Callable[[Path, str], Backend]


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
    options: DecodingOptions | None = None,
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
    factory = backend_factory or faster_whisper_backend
    decoding = options or DecodingOptions()
    extra: dict[str, Any] = {}
    if decoding.initial_prompt:
        extra["initial_prompt"] = decoding.initial_prompt
    if decoding.hotwords:
        extra["hotwords"] = decoding.hotwords
    device = "cuda" if decoding.device == "auto" and cuda_device_count() else "cpu"
    device_note: str | None = None
    try:
        try:
            raw_segments, info = _start(
                factory, model_path, device, audio, language, extra
            )
        except (ModelDownloadError, TranscriptionCancelled):
            raise
        except Exception as error:  # noqa: BLE001 — GPU zawiodło → CPU
            if device == "cpu":
                raise
            device, device_note = "cpu", _short(error)
            raw_segments, info = _start(
                factory, model_path, device, audio, language, extra
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
        device=device,
        device_note=device_note,
    )


def _start(
    factory: BackendFactory,
    model_path: Path,
    device: str,
    audio: Path,
    language: str,
    extra: dict[str, Any],
) -> tuple[Iterable[Any], Any]:
    """Ładuje backend i uruchamia dekodowanie.

    Na GPU pierwszy segment jest pobierany od razu: brak bibliotek CUDA
    ujawnia się dopiero przy pierwszym kodowaniu, a wtedy można jeszcze
    bezpiecznie przejść na CPU.
    """
    backend = factory(model_path, device)
    raw_segments, info = backend.transcribe(
        str(audio), language=language, vad_filter=True, **extra
    )
    if device == "cpu":
        return raw_segments, info
    iterator = iter(raw_segments)
    first = next(iterator, None)
    if first is None:
        return (), info
    return itertools.chain((first,), iterator), info


def _short(error: Exception) -> str:
    text = " ".join(str(error).split()) or type(error).__name__
    if len(text) > _DEVICE_NOTE_MAX_CHARS:
        text = text[: _DEVICE_NOTE_MAX_CHARS - 1] + "…"
    return text


def build_hotwords(*vocabularies: Iterable[str]) -> str | None:
    """Słownik dla Whispera: suma list bez powtórzeń, w kolejności podania.

    Hasła są przycinane z białych znaków, a całość ograniczona do
    ``PROMPT_MAX_CHARS`` — hasła, które się nie mieszczą, są pomijane.
    """
    seen: set[str] = set()
    words: list[str] = []
    length = 0
    for vocabulary in vocabularies:
        for raw in vocabulary:
            word = " ".join(raw.split())
            key = word.casefold()
            if not word or key in seen:
                continue
            added = len(word) + (1 if words else 0)
            if length + added > PROMPT_MAX_CHARS:
                continue
            seen.add(key)
            words.append(word)
            length += added
    return " ".join(words) or None


def _confidence(avg_logprob: float) -> float:
    """Przybliżona pewność segmentu z logarytmu prawdopodobieństwa."""
    return round(min(1.0, max(0.0, math.exp(avg_logprob))), 3)


def faster_whisper_backend(model_dir: Path, device: str = "cpu") -> Backend:
    """Ładuje model faster-whisper wyłącznie z lokalnych plików (offline)."""
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_dir),
        device=device,
        compute_type="int8_float16" if device == "cuda" else "int8",
        local_files_only=True,
    )


__all__ = [
    "Backend",
    "DecodingOptions",
    "build_hotwords",
    "SegmentResult",
    "TranscriptionCancelled",
    "TranscriptionError",
    "TranscriptionResult",
    "transcribe",
]
