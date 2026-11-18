"""Silnik transkrypcji ASR: lokalne wykonanie, anulowanie, wynik z pewnością.

Moduły pakietu: ``results.py`` (wynik i szkic do edytora), ``backend.py``
(kontrakt backendu i fabryka faster-whisper), ``chunked.py`` (transkrypcja
fragmentami); tutaj - ``transcribe``, opcje dekodowania, walidacja wejścia
i normalizacja błędów.

Granica modułu: brak zależności od GUI ani Qt. Wykonanie jest synchroniczne
i kooperacyjnie anulowane między segmentami - wątek tła dostarcza warstwa UI.

Model jest ładowany wyłącznie z lokalnego katalogu (``local_files_only``),
więc po pobraniu transkrypcja nie generuje ruchu sieciowego (ACC-11).
Dekodowanie audio (MP3, WAV, FLAC, AAC itd.) realizuje faster-whisper przez PyAV/FFmpeg.

Urządzenie ``auto`` używa karty CUDA, gdy CTranslate2 ją widzi; błąd
ładowania modelu lub pierwszego dekodowania na GPU (np. brak bibliotek
cuBLAS/cuDNN) powoduje ponowienie na CPU z informacją w wyniku (ACC-37).

faster-whisper liczy cechy (spektrogram) dla całego podanego nagrania naraz,
więc zużycie pamięci rośnie liniowo z jego długością - godzinne nagranie
potrafi zająć kilka GB. Opcja ``DecodingOptions.chunked`` włącza
:class:`ChunkedWhisperBackend`, który dekoduje plik raz i podaje modelowi
kolejne kilkuminutowe fragmenty cięte w ciszy, dzięki czemu szczyt pamięci
nie zależy od długości nagrania.

``DecodingOptions.diarize`` dzieli wynik na mówców (``asr/diarization.py``)
po zakończeniu transkrypcji całego nagrania; błąd diaryzacji nie przekreśla
transkrypcji - wynik jest wtedy bez mówców, z przyczyną w
``TranscriptionResult.diarization_note``.

``DecodingOptions.clip`` ogranicza transkrypcję do fragmentu nagrania (pętla
A-B). Fragment jest wycinany z próbek tym samym backendem co transkrypcja
fragmentami, a czasy segmentów i słów pozostają bezwzględne. Nie używamy
``clip_timestamps`` faster-whispera: wyłącza on VAD i liczy cechy dla całego
nagrania.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from transkryptor.asr import backend as backend_module
from transkryptor.asr import diarization
from transkryptor.asr.backend import BackendFactory, faster_whisper_backend
from transkryptor.asr.chunked import ChunkDone, ChunkedWhisperBackend
from transkryptor.asr.diarization import DiarizationCancelled, EmbedderFactory
from transkryptor.asr.models import DEFAULT_MODEL, AsrModelInfo
from transkryptor.asr.results import (
    SegmentResult,
    TranscriptionResult,
    confidence_of,
    words_of,
)
from transkryptor.asr.system import cuda_device_count
from transkryptor.errors import AppError, ModelDownloadError
from transkryptor.i18n import tr

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

logger = logging.getLogger(__name__)

LANGUAGE = "pl"
# Fragmenty natywnych komunikatów o braku pamięci (CTranslate2/MKL, C++, numpy).
_OUT_OF_MEMORY_MARKERS = (
    "failed to allocate",
    "bad_alloc",
    "out of memory",
    "unable to allocate",
)

DEVICES = ("auto", "cpu")
# Limit podpowiedzi kontekstowej i słownika: okno promptu Whispera to
# 224 tokeny, a długi prompt sprzyja halucynacjom (powtarzaniu promptu).
PROMPT_MAX_CHARS = 200
# Podpowiedź stylu „zapis dosłowny” (zgłoszenia #46 i #45): Whisper
# naśladuje styl promptu, więc przykład mowy z powtórzeniami i fatycznym
# „nie?” sprawia, że nie wygładza ich w szkicu. Pomiar na wywiadzie gwarowym
# (model medium): dwa razy więcej „nie?”, wraca m.in. „no no”; frazy
# promptu nie przenikają do tekstu.
VERBATIM_PROMPT = (
    "No no, to to było tak, nie? Ja ja nie wiem, nie? No i i tam tam chodzili,"
    " nie? Eee… to to som zabobony, nie? No no, tak tak mówiom, nie?"
)
_DEVICE_NOTE_MAX_CHARS = 200
# Część paska postępu przypadająca na transkrypcję, gdy po niej działa
# diaryzacja (reszta to podział na mówców).
DIARIZED_ASR_SHARE = 0.85


class TranscriptionCancelled(Exception):
    """Transkrypcja przerwana na życzenie użytkownika (nie jest błędem)."""


class TranscriptionError(AppError):
    """Nie udało się wykonać lokalnej transkrypcji."""


@dataclass(frozen=True)
class DecodingOptions:
    """Parametry transkrypcji wybrane przez użytkownika (REQ-10, REQ-21).

    ``initial_prompt`` i ``hotwords`` trafiają do Whispera tylko, gdy nie są
    puste - bez nich zachowanie jest takie jak przed fazą 09. ``chunked``
    włącza transkrypcję fragmentami (mniej pamięci przy długich nagraniach).
    ``word_timestamps`` dodaje do segmentów słowa z czasami i pewnością,
    a ``clip`` (sekundy od-do) ogranicza transkrypcję do fragmentu (faza 11).
    ``diarize`` dzieli wynik na mówców modelem z ``diarization_dir``; wymaga
    słów z czasami (włącza je) i nie dotyczy fragmentu (``clip``) - numery
    mówców fragmentu nie zgadzałyby się z całym nagraniem. ``speakers`` to
    znana liczba mówców (None: wyznaczana automatycznie).
    """

    device: str = "auto"
    initial_prompt: str | None = None
    hotwords: str | None = None
    chunked: bool = False
    word_timestamps: bool = False
    clip: tuple[float, float] | None = None
    diarize: bool = False
    diarization_dir: Path | None = None
    speakers: int | None = None

    @property
    def diarizes(self) -> bool:
        """Czy ta transkrypcja kończy się podziałem na mówców."""
        return self.diarize and self.diarization_dir is not None and self.clip is None


CancelCheck = Callable[[], bool]
SegmentCallback = Callable[[SegmentResult], None]
ProgressCallback = Callable[[float], None]  # ułamek nagrania 0.0-1.0


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
    embedder_factory: EmbedderFactory | None = None,
    decode: Callable[[str], npt.NDArray[np.float32]] | None = None,
) -> TranscriptionResult:
    """Wykonuje lokalną transkrypcję pliku audio.

    Podnosi :class:`ModelDownloadError`, gdy model nie jest kompletny,
    :class:`TranscriptionCancelled` przy anulowaniu oraz
    :class:`TranscriptionError` przy błędzie wykonania.

    ``on_progress`` dostaje po każdym segmencie ułamek przetworzonego
    nagrania (koniec segmentu względem długości audio); nie jest wołane,
    gdy backend nie zna długości nagrania. Przy diaryzacji transkrypcja
    zajmuje ``DIARIZED_ASR_SHARE`` postępu, a podział na mówców - resztę.
    ``embedder_factory`` i ``decode`` podstawiają testy.
    """
    cancel = should_cancel or (lambda: False)
    audio, model_path = _checked_inputs(audio_path, model_dir, model)
    if cancel():
        raise TranscriptionCancelled()
    decoding = options or DecodingOptions()
    raw_segments, info, device, device_note = _start_with_fallback(
        backend_factory or faster_whisper_backend,
        model_path,
        audio,
        language,
        decoding,
    )
    share = DIARIZED_ASR_SHARE if decoding.diarizes else 1.0
    segments = _collect_segments(
        raw_segments,
        _clip_span(info, decoding),
        cancel,
        on_segment,
        None if on_progress is None else lambda fraction: on_progress(fraction * share),
    )
    if cancel():
        raise TranscriptionCancelled()
    diarization_note: str | None = None
    if decoding.diarizes and segments:
        segments, diarization_note = _diarize(
            segments,
            audio,
            decoding,
            cancel,
            (
                None
                if on_progress is None
                else lambda fraction: on_progress(share + (1 - share) * fraction)
            ),
            embedder_factory,
            decode,
        )
    if cancel():
        raise TranscriptionCancelled()
    return TranscriptionResult(
        text="".join(segment.text for segment in segments).strip(),
        language=getattr(info, "language", language),
        segments=tuple(segments),
        device=device,
        device_note=device_note,
        diarization_note=diarization_note,
    )


def _checked_inputs(
    audio_path: str | Path, model_dir: str | Path, model: AsrModelInfo
) -> tuple[Path, Path]:
    """Ścieżki nagrania i modelu; błąd, gdy nagrania nie ma albo model niepełny."""
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
    return audio, model_path


def _backend_kwargs(decoding: DecodingOptions) -> dict[str, Any]:
    """Opcjonalne argumenty backendu - przekazywane tylko, gdy są ustawione."""
    extra: dict[str, Any] = {}
    if decoding.initial_prompt:
        extra["initial_prompt"] = decoding.initial_prompt
    if decoding.hotwords:
        extra["hotwords"] = decoding.hotwords
    if decoding.word_timestamps or decoding.diarizes:
        extra["word_timestamps"] = True
    return extra


def _start_with_fallback(
    factory: BackendFactory,
    model_path: Path,
    audio: Path,
    language: str,
    decoding: DecodingOptions,
) -> tuple[Iterable[Any], Any, str, str | None]:
    """Uruchamia dekodowanie na GPU (gdy wybrane i dostępne), a po błędzie na CPU.

    Zwraca segmenty, info backendu, użyte urządzenie i powód przejścia na CPU.
    """
    extra = _backend_kwargs(decoding)
    device = "cuda" if decoding.device == "auto" and cuda_device_count() else "cpu"
    device_note: str | None = None
    try:
        try:
            raw_segments, info = _start(
                factory, model_path, device, audio, language, extra, decoding
            )
        except (ModelDownloadError, TranscriptionCancelled):
            raise
        except Exception as error:  # GPU zawiodło → CPU
            if device == "cpu":
                raise
            device, device_note = "cpu", _short(error)
            raw_segments, info = _start(
                factory, model_path, device, audio, language, extra, decoding
            )
    except (ModelDownloadError, TranscriptionCancelled):
        raise
    except Exception as error:  # normalizacja do AppError
        raise transcription_error(error) from error
    return raw_segments, info, device, device_note


def _clip_span(info: Any, decoding: DecodingOptions) -> tuple[float, float]:
    """Początek i długość transkrybowanego fragmentu (cały plik albo wycinek)."""
    duration = float(getattr(info, "duration", 0) or 0)
    if decoding.clip is None:
        return 0.0, duration
    origin = decoding.clip[0]
    return origin, max(0.0, min(duration, decoding.clip[1]) - origin)


def _collect_segments(
    raw_segments: Iterable[Any],
    span: tuple[float, float],
    cancel: CancelCheck,
    on_segment: SegmentCallback | None,
    on_progress: ProgressCallback | None,
) -> list[SegmentResult]:
    """Zamienia segmenty backendu na ``SegmentResult`` z postępem i anulowaniem."""
    origin, duration = span
    progress = 0.0

    def report(end_s: float) -> None:
        nonlocal progress
        if on_progress is not None and duration > 0:
            # Segmenty idą chronologicznie, ale max() chroni przed cofaniem.
            progress = max(progress, min(1.0, (end_s - origin) / duration))
            on_progress(progress)

    segments: list[SegmentResult] = []
    for raw in _guarded(raw_segments):
        if cancel():
            raise TranscriptionCancelled()
        if isinstance(raw, ChunkDone):
            # Kawałek bez mowy (cisza, muzyka) też posuwa postęp (zgł. #38).
            report(raw.end)
            continue
        segment = SegmentResult(
            start_s=float(raw.start),
            end_s=float(raw.end),
            text=raw.text,
            confidence=confidence_of(raw.avg_logprob),
            words=words_of(raw),
        )
        segments.append(segment)
        if on_segment is not None:
            on_segment(segment)
        report(segment.end_s)
    return segments


def _diarize(
    segments: list[SegmentResult],
    audio: Path,
    decoding: DecodingOptions,
    cancel: CancelCheck,
    on_progress: ProgressCallback | None,
    embedder_factory: EmbedderFactory | None,
    decode: Callable[[str], npt.NDArray[np.float32]] | None,
) -> tuple[list[SegmentResult], str | None]:
    """Przypisuje mówców segmentom; błąd zostawia szkic bez mówców (z notą)."""
    if decoding.diarization_dir is None:
        return segments, None
    try:
        samples = (decode or backend_module.decode_audio)(str(audio))
        turns = diarization.diarize(
            samples,
            decoding.diarization_dir,
            _speech(segments),
            should_cancel=cancel,
            on_progress=on_progress,
            speakers=decoding.speakers,
            factory=embedder_factory,
        )
    except DiarizationCancelled:
        raise TranscriptionCancelled() from None
    except Exception as error:  # szkic bez mówców
        logger.warning("Speaker diarization failed", exc_info=error)
        return segments, _short(error)
    return list(diarization.assign_speakers(segments, turns)), None


def _speech(segments: Iterable[SegmentResult]) -> list[tuple[float, float]]:
    """Fragmenty mowy dla diaryzacji: słowa, a bez słów - cały segment."""
    spans: list[tuple[float, float]] = []
    for segment in segments:
        if segment.words:
            spans.extend((word.start_s, word.end_s) for word in segment.words)
        else:
            spans.append((segment.start_s, segment.end_s))
    return spans


def _start(
    factory: BackendFactory,
    model_path: Path,
    device: str,
    audio: Path,
    language: str,
    extra: dict[str, Any],
    decoding: DecodingOptions,
) -> tuple[Iterable[Any], Any]:
    """Ładuje backend i uruchamia dekodowanie (opcjonalnie fragmentami).

    Na GPU pierwszy segment jest pobierany od razu: brak bibliotek CUDA
    ujawnia się dopiero przy pierwszym kodowaniu, a wtedy można jeszcze
    bezpiecznie przejść na CPU.
    """
    backend = factory(model_path, device)
    if decoding.chunked or decoding.clip is not None:
        backend = ChunkedWhisperBackend(backend, clip=decoding.clip)
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


def _guarded(raw_segments: Iterable[Any]) -> Iterator[Any]:
    """Iteruje segmenty backendu, normalizując jego błędy do AppError.

    faster-whisper dekoduje leniwie, więc błąd (np. brak pamięci) może
    wystąpić dopiero przy pobieraniu kolejnego segmentu.
    """
    iterator = iter(raw_segments)
    while True:
        try:
            raw = next(iterator)
        except StopIteration:
            return
        except Exception as error:  # normalizacja do AppError
            raise transcription_error(error) from error
        yield raw


def transcription_error(error: Exception) -> TranscriptionError:
    """Buduje komunikat dla użytkownika; brak pamięci dostaje własny."""
    if is_out_of_memory(error):
        return TranscriptionError(
            user_message=tr("asr.error.out_of_memory"),
            retry_hint=tr("asr.error.out_of_memory.hint"),
        )
    return TranscriptionError(
        user_message=tr("asr.error.transcribe", reason=error),
        retry_hint=tr("asr.error.transcribe.hint"),
    )


def is_out_of_memory(error: BaseException) -> bool:
    """Czy wyjątek oznacza brak pamięci (Python lub natywne biblioteki)."""
    if isinstance(error, MemoryError):
        return True
    message = str(error).lower()
    return any(marker in message for marker in _OUT_OF_MEMORY_MARKERS)


def _short(error: Exception) -> str:
    text = " ".join(str(error).split()) or type(error).__name__
    if len(text) > _DEVICE_NOTE_MAX_CHARS:
        text = text[: _DEVICE_NOTE_MAX_CHARS - 1] + "…"
    return text


def compose_prompt(context: str, *, verbatim: bool) -> str | None:
    """Prompt Whispera: styl zapisu dosłownego, a po nim kontekst nagrania.

    Kontekst jest na końcu - gdy prompt z hasłami przekroczy okno Whispera,
    faster-whisper obcina go od początku, więc traci się najpierw przykład
    stylu, a nie treść wpisana przez użytkownika.
    """
    parts = [VERBATIM_PROMPT] if verbatim else []
    if context.strip():
        parts.append(context.strip())
    return " ".join(parts) or None


def build_hotwords(*vocabularies: Iterable[str]) -> str | None:
    """Słownik dla Whispera: suma list bez powtórzeń, w kolejności podania.

    Hasła są przycinane z białych znaków, a całość ograniczona do
    ``PROMPT_MAX_CHARS`` - hasła, które się nie mieszczą, są pomijane.
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


__all__ = [
    "LANGUAGE",
    "CancelCheck",
    "DecodingOptions",
    "ProgressCallback",
    "SegmentCallback",
    "TranscriptionCancelled",
    "TranscriptionError",
    "build_hotwords",
    "compose_prompt",
    "is_out_of_memory",
    "transcribe",
    "transcription_error",
]
