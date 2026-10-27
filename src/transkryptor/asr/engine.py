"""Silnik transkrypcji ASR: lokalne wykonanie, anulowanie, wynik z pewnością.

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
import math
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol

from transkryptor.asr import diarization
from transkryptor.asr.diarization import DiarizationCancelled, EmbedderFactory
from transkryptor.asr.models import DEFAULT_MODEL, AsrModelInfo
from transkryptor.asr.system import cuda_device_count
from transkryptor.errors import AppError, ModelDownloadError
from transkryptor.i18n import tr

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

logger = logging.getLogger(__name__)

LANGUAGE = "pl"
SAMPLE_RATE = 16_000
# Długość fragmentu przy transkrypcji fragmentami. Szczyt pamięci cech dla
# 5 minut to ok. 0,3 GB; dłuższe fragmenty nie poprawiają jakości (Whisper
# i tak pracuje w oknach 30 s), a krótsze mnożą cięcia.
CHUNK_S = 300.0
# Okno przed nominalnym końcem fragmentu, w którym szukamy najcichszego
# miejsca na cięcie, żeby nie przecinać słów.
CUT_SEARCH_S = 20.0
CUT_FRAME_S = 0.1
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
_DEVICE_NOTE_MAX_CHARS = 200
# Najdłuższy wers szkicu (w sekundach nagrania) - wers zaczyna się
# znacznikiem czasu, by tekst i eksport nie były jednym blokiem.
DRAFT_LINE_SECONDS = 30.0
# Część paska postępu przypadająca na transkrypcję, gdy po niej działa
# diaryzacja (reszta to podział na mówców).
DIARIZED_ASR_SHARE = 0.85


class TranscriptionCancelled(Exception):
    """Transkrypcja przerwana na życzenie użytkownika (nie jest błędem)."""


class TranscriptionError(AppError):
    """Nie udało się wykonać lokalnej transkrypcji."""


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


class Backend(Protocol):
    """Kontrakt backendu zgodny z ``faster_whisper.WhisperModel.transcribe``.

    Zwraca parę (iterowalne_segmenty, info); segmenty mają ``start``,
    ``end``, ``text`` i ``avg_logprob``, a info opcjonalnie ``language``
    i ``duration``. Niepuste ``initial_prompt`` i ``hotwords`` oraz
    ``word_timestamps=True`` są przekazywane dodatkowo jako argumenty
    nazwane; segmenty mają wtedy ``words`` (``start``, ``end``, ``word``,
    ``probability``).
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
    segments: list[SegmentResult] = []
    for raw in _guarded(raw_segments):
        if cancel():
            raise TranscriptionCancelled()
        segment = SegmentResult(
            start_s=float(raw.start),
            end_s=float(raw.end),
            text=raw.text,
            confidence=_confidence(raw.avg_logprob),
            words=_words(raw),
        )
        segments.append(segment)
        if on_segment is not None:
            on_segment(segment)
        if on_progress is not None and duration > 0:
            # Segmenty idą chronologicznie, ale max() chroni przed cofaniem.
            progress = max(progress, min(1.0, (segment.end_s - origin) / duration))
            on_progress(progress)
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
        samples = (decode or _decode_audio)(str(audio))
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


def _words(raw: Any, offset: float = 0.0) -> tuple[WordResult, ...]:
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


def _confidence(avg_logprob: float) -> float:
    """Przybliżona pewność segmentu z logarytmu prawdopodobieństwa."""
    return round(min(1.0, max(0.0, math.exp(avg_logprob))), 3)


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


class ChunkedWhisperBackend:
    """Backend zgodny z :class:`Backend`, transkrybujący nagranie fragmentami.

    Nagranie jest dekodowane raz (ok. 0,25 GB na godzinę), a model dostaje
    kolejne fragmenty jako tablice próbek; czasy segmentów są przesuwane
    o początek fragmentu. ``clip`` (sekundy od-do) ogranicza pracę do
    jednego zakresu nagrania.
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
        self._decode = decode or _decode_audio
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
    ) -> Iterator[_ShiftedSegment]:
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
                        for w in _words(raw, offset)
                    ),
                )


def _decode_audio(audio: str) -> npt.NDArray[np.float32]:
    from faster_whisper.audio import decode_audio

    samples: npt.NDArray[np.float32] = decode_audio(audio, sampling_rate=SAMPLE_RATE)
    return samples


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
    "ChunkedWhisperBackend",
    "DecodingOptions",
    "build_hotwords",
    "draft_line_speakers",
    "draft_text",
    "SegmentResult",
    "WordResult",
    "TranscriptionCancelled",
    "TranscriptionError",
    "TranscriptionResult",
    "chunk_bounds",
    "is_out_of_memory",
    "transcribe",
    "transcription_error",
]
