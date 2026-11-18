"""Podproces roboczy ASR: model w pamięci i natychmiastowe anulowanie (PERF-04).

Wczytanie modelu Whisper (~1,5 GB wag) trwa długo, a faster-whisper przed
pierwszym segmentem dekoduje całe nagranie i wykrywa mowę - w tym czasie
kooperacyjne anulowanie z ``engine.transcribe`` nie ma kiedy zadziałać.
Dlatego transkrypcja biegnie w osobnym procesie (``multiprocessing``,
kontekst ``spawn`` - ten sam na Linuksie i Windows):

- proces trzyma wczytany backend między transkrypcjami (bufor po katalogu
  modelu i urządzeniu), więc kolejna transkrypcja nie wczytuje modelu od nowa;
- „Anuluj” po pierwszym segmencie najpierw prosi proces o przerwanie
  (``multiprocessing.Event`` sprawdzany między segmentami) i czeka do
  ``CANCEL_GRACE_S`` - model zostaje wtedy w pamięci, a kolejna transkrypcja
  nie wczytuje go od nowa. Przed pierwszym segmentem (dekodowanie i wykrywanie
  mowy bez punktu anulowania) albo gdy proces nie odpowie w tym czasie,
  proces jest kończony od razu (``terminate``) i następna transkrypcja
  uruchomi nowy proces;
- po ``IDLE_TIMEOUT_S`` bez pracy proces sam się kończy i zwalnia pamięć.

:meth:`AsrWorker.transcribe` ma kontrakt ``engine.transcribe`` (te same
wywołania zwrotne i wyjątki), więc warstwa UI podstawia go bez zmian.
Walidacja (brak nagrania, brak modelu) i normalizacja błędów zostają
w ``engine.transcribe``, wołanym w procesie roboczym.

Moduł nie zależy od Qt. Wydanie (PyInstaller) wymaga
``multiprocessing.freeze_support()`` w punkcie wejścia.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from transkryptor import diagnostics
from transkryptor.asr import engine
from transkryptor.asr.backend import Backend, BackendFactory, faster_whisper_backend
from transkryptor.asr.engine import (
    LANGUAGE,
    CancelCheck,
    DecodingOptions,
    ProgressCallback,
    SegmentCallback,
    TranscriptionCancelled,
    TranscriptionError,
)
from transkryptor.asr.models import DEFAULT_MODEL, AsrModelInfo
from transkryptor.asr.results import TranscriptionResult
from transkryptor.errors import AppError, ModelDownloadError
from transkryptor.i18n import current_language, set_language, tr

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 0.1
STOP_TIMEOUT_S = 2.0
CANCEL_GRACE_S = 1.0

# Błędy przekazywane z procesu roboczego: nazwa klasy → klasa.
_ERRORS: dict[str, type[AppError]] = {
    "ModelDownloadError": ModelDownloadError,
    "TranscriptionError": TranscriptionError,
}


class AsrWorker:
    """Właściciel procesu roboczego ASR; jedna transkrypcja naraz.

    ``backend_factory`` musi być funkcją najwyższego poziomu (przekazywaną
    do procesu przez pickle); None = faster-whisper.
    """

    def __init__(
        self,
        backend_factory: BackendFactory | None = None,
        idle_timeout_s: float = IDLE_TIMEOUT_S,
    ) -> None:
        self._backend_factory = backend_factory
        self._idle_timeout_s = idle_timeout_s
        self._process: BaseProcess | None = None
        self._conn: Connection | None = None
        self._cancel_event: Any = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def transcribe(
        self,
        audio_path: str | Path,
        model_dir: str | Path,
        *,
        model: AsrModelInfo = DEFAULT_MODEL,
        should_cancel: CancelCheck | None = None,
        on_segment: SegmentCallback | None = None,
        on_progress: ProgressCallback | None = None,
        language: str = LANGUAGE,
        options: DecodingOptions | None = None,
    ) -> TranscriptionResult:
        """Transkrypcja w procesie roboczym (kontrakt ``engine.transcribe``)."""
        cancel = should_cancel or (lambda: False)
        request = (
            "transcribe",
            str(audio_path),
            str(model_dir),
            model,
            language,
            options or DecodingOptions(),
        )
        with self._lock:
            if cancel():
                raise TranscriptionCancelled()
            try:
                return self._run(request, cancel, on_segment, on_progress)
            except _WorkerExited:
                # Proces mógł zakończyć się po bezczynności tuż przed
                # zleceniem - jedna ponowna próba w nowym procesie.
                try:
                    return self._run(request, cancel, on_segment, on_progress)
                except _WorkerExited as exited:
                    raise _crash_error() from exited

    def ping(self, timeout_s: float = 30.0) -> bool:
        """Uruchamia proces i sprawdza odpowiedź (``--self-test``)."""
        with self._lock:
            conn = self._ensure_started()
            conn.send(("ping",))
            if not conn.poll(timeout_s):
                return False
            return bool(conn.recv() == ("pong", None))

    def shutdown(self) -> None:
        """Kończy proces roboczy (zamknięcie aplikacji, zwolnienie pamięci)."""
        conn, process = self._conn, self._process
        self._conn = None
        self._process = None
        if process is not None and process.is_alive() and conn is not None:
            with contextlib.suppress(OSError):
                conn.send(("stop",))
            process.join(STOP_TIMEOUT_S)
        _terminate(process, conn)

    # --- wewnętrzne -----------------------------------------------------------

    def _run(
        self,
        request: tuple[Any, ...],
        cancel: CancelCheck,
        on_segment: SegmentCallback | None,
        on_progress: ProgressCallback | None,
    ) -> TranscriptionResult:
        conn = self._ensure_started()
        if self._cancel_event is not None:
            self._cancel_event.clear()
        try:
            conn.send(request)
        except OSError as error:
            self._kill()
            raise _WorkerExited() from error
        received = False
        segments_seen = False
        while True:
            if cancel():
                self._cancel(conn, graceful=segments_seen)
                raise TranscriptionCancelled()
            try:
                if not conn.poll(POLL_INTERVAL_S):
                    if not self.is_running():
                        raise EOFError
                    continue
                kind, payload = conn.recv()
            except (EOFError, OSError) as error:
                self._log_exit()
                self._kill()
                if received:
                    raise _crash_error() from error
                raise _WorkerExited() from error
            received = True
            segments_seen = segments_seen or kind == "segment"
            result = _handle_message(kind, payload, on_segment, on_progress)
            if result is not None:
                return result

    def _cancel(self, conn: Connection, *, graceful: bool) -> None:
        """Przerywa transkrypcję; proces zostaje, gdy przerwie ją sam.

        Po pierwszym segmencie proces sprawdza zdarzenie anulowania między
        segmentami - czekamy na jego odpowiedź najwyżej ``CANCEL_GRACE_S``.
        Inaczej (albo bez odpowiedzi) proces jest kończony.
        """
        if not graceful or self._cancel_event is None:
            self._kill()
            return
        self._cancel_event.set()
        deadline = time.monotonic() + CANCEL_GRACE_S
        try:
            while (left := deadline - time.monotonic()) > 0:
                if not conn.poll(left):
                    break
                kind, _payload = conn.recv()
                if kind in {"cancelled", "done", "error"}:
                    return
        except (EOFError, OSError):
            pass
        self._kill()

    def _ensure_started(self) -> Connection:
        if self._conn is not None and self.is_running():
            return self._conn
        self._kill()
        context = multiprocessing.get_context("spawn")
        parent_conn, child_conn = context.Pipe()
        cancel_event = context.Event()
        process = context.Process(
            target=_serve,
            args=(
                child_conn,
                self._backend_factory,
                current_language(),
                self._idle_timeout_s,
                _crash_log_dir(),
                cancel_event,
            ),
            name="transkryptor-asr",
            daemon=True,
        )
        process.start()
        child_conn.close()
        self._process = process
        self._conn = parent_conn
        self._cancel_event = cancel_event
        return parent_conn

    def _log_exit(self) -> None:
        """Dziennik: proces zakończył się inaczej niż po bezczynności."""
        process = self._process
        if process is None:
            return
        process.join(POLL_INTERVAL_S)
        if process.exitcode == 0:
            return
        logger.error(
            "ASR worker process exited unexpectedly (exit code %s)", process.exitcode
        )
        diagnostics.collect_crash_report()

    def _kill(self) -> None:
        conn, process = self._conn, self._process
        self._conn = None
        self._process = None
        self._cancel_event = None
        _terminate(process, conn)


def _handle_message(
    kind: str,
    payload: Any,
    on_segment: SegmentCallback | None,
    on_progress: ProgressCallback | None,
) -> TranscriptionResult | None:
    """Wiadomość z procesu roboczego; wynik albo None, gdy praca trwa dalej."""
    if kind == "segment" and on_segment is not None:
        on_segment(payload)
    elif kind == "progress" and on_progress is not None:
        on_progress(payload)
    elif kind == "done":
        result: TranscriptionResult = payload
        return result
    elif kind == "cancelled":
        raise TranscriptionCancelled()
    elif kind == "error":
        name, user_message, retry_hint, details = payload
        logger.error("ASR worker reported %s:\n%s", name, details)
        raise _ERRORS.get(name, TranscriptionError)(
            user_message=user_message, retry_hint=retry_hint
        )
    return None


class _WorkerExited(Exception):
    """Proces roboczy zakończył się, zanim odpowiedział na zlecenie."""


def _crash_log_dir() -> str | None:
    """Katalog zapisu awarii dla procesu roboczego - tylko gdy dziennik działa."""
    directory = diagnostics.active_log_dir()
    return None if directory is None else str(directory)


def _crash_error() -> TranscriptionError:
    return TranscriptionError(
        user_message=tr("asr.error.worker_crashed"),
        retry_hint=tr("asr.error.out_of_memory.hint"),
    )


def _terminate(process: BaseProcess | None, conn: Connection | None) -> None:
    if process is not None and process.is_alive():
        process.terminate()
        process.join(STOP_TIMEOUT_S)
        if process.is_alive():
            process.kill()
            process.join(STOP_TIMEOUT_S)
    if conn is not None:
        conn.close()


# --- proces roboczy -------------------------------------------------------------


def _serve(
    conn: Connection,
    backend_factory: BackendFactory | None,
    language: str,
    idle_timeout_s: float,
    crash_log_dir: str | None = None,
    cancel_event: Any = None,
) -> None:
    """Pętla procesu roboczego: zlecenia z potoku, bufor backendu.

    ``cancel_event`` (``multiprocessing.Event``) ustawia rodzic, gdy
    użytkownik anuluje transkrypcję po pierwszym segmencie.
    """
    should_cancel = cancel_event.is_set if cancel_event is not None else (lambda: False)
    set_language(language)
    if crash_log_dir is not None:
        # Awaria natywna (np. CTranslate2) kończy proces bez odpowiedzi -
        # ślad stosu zostaje w ``crash.log`` dla dziennika procesu głównego.
        diagnostics.enable_crash_log(Path(crash_log_dir))
    cached: dict[tuple[Path, str], Backend] = {}
    factory = backend_factory or faster_whisper_backend

    def cached_factory(model_dir: Path, device: str) -> Backend:
        key = (model_dir, device)
        backend = cached.get(key)
        if backend is None:
            cached.clear()  # jeden model naraz - zwalnia poprzedni
            backend = factory(model_dir, device)
            cached[key] = backend
        return backend

    while conn.poll(idle_timeout_s):
        try:
            request = conn.recv()
        except (EOFError, OSError):
            return
        command = request[0]
        if command == "stop":
            return
        if command == "ping":
            conn.send(("pong", None))
            continue
        if command == "transcribe":
            _, audio_path, model_dir, model, request_language, options = request
            conn.send(
                _transcribe_request(
                    conn,
                    cached_factory,
                    audio_path,
                    model_dir,
                    model,
                    request_language,
                    options,
                    should_cancel,
                )
            )


def _transcribe_request(
    conn: Connection,
    factory: Callable[[Path, str], Backend],
    audio_path: str,
    model_dir: str,
    model: AsrModelInfo,
    language: str,
    options: DecodingOptions,
    should_cancel: CancelCheck,
) -> tuple[str, Any]:
    try:
        result = engine.transcribe(
            audio_path,
            model_dir,
            model=model,
            should_cancel=should_cancel,
            on_segment=lambda segment: conn.send(("segment", segment)),
            on_progress=lambda fraction: conn.send(("progress", fraction)),
            backend_factory=factory,
            language=language,
            options=options,
        )
    except TranscriptionCancelled:
        return "cancelled", None
    except AppError as error:
        return "error", (
            type(error).__name__,
            error.user_message,
            error.retry_hint,
            diagnostics.format_exception(error),
        )
    except Exception as error:  # noqa: BLE001 - błąd zgłaszany rodzicowi
        app_error = engine.transcription_error(error)
        return "error", (
            "TranscriptionError",
            app_error.user_message,
            app_error.retry_hint,
            diagnostics.format_exception(error),
        )
    return "done", result


__all__ = ["AsrWorker"]
