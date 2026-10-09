"""Podproces roboczy ASR: model w pamięci i natychmiastowe anulowanie (PERF-04).

Wczytanie modelu Whisper (~1,5 GB wag) trwa długo, a faster-whisper przed
pierwszym segmentem dekoduje całe nagranie i wykrywa mowę — w tym czasie
kooperacyjne anulowanie z ``engine.transcribe`` nie ma kiedy zadziałać.
Dlatego transkrypcja biegnie w osobnym procesie (``multiprocessing``,
kontekst ``spawn`` — ten sam na Linuksie i Windows):

- proces trzyma wczytany backend między transkrypcjami (bufor po katalogu
  modelu), więc kolejna transkrypcja nie wczytuje modelu od nowa;
- „Anuluj” kończy proces od razu (``terminate``) — następna transkrypcja
  uruchomi nowy proces i wczyta model ponownie;
- po ``IDLE_TIMEOUT_S`` bez pracy proces sam się kończy i zwalnia pamięć.

:meth:`AsrWorker.transcribe` ma kontrakt ``engine.transcribe`` (te same
wywołania zwrotne i wyjątki), więc warstwa UI podstawia go bez zmian.
Walidacja (brak nagrania, brak modelu) i normalizacja błędów zostają
w ``engine.transcribe``, wołanym w procesie roboczym.

Moduł nie zależy od Qt. Wydanie (PyInstaller) wymaga
``multiprocessing.freeze_support()`` w punkcie wejścia.
"""

from __future__ import annotations

import multiprocessing
import threading
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from transkryptor.asr import engine
from transkryptor.asr.engine import (
    LANGUAGE,
    Backend,
    BackendFactory,
    CancelCheck,
    ProgressCallback,
    SegmentCallback,
    TranscriptionCancelled,
    TranscriptionError,
    TranscriptionResult,
)
from transkryptor.asr.models import DEFAULT_MODEL, AsrModelInfo
from transkryptor.errors import AppError, ModelDownloadError
from transkryptor.i18n import current_language, set_language, tr

IDLE_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 0.1
STOP_TIMEOUT_S = 2.0

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
    ) -> TranscriptionResult:
        """Transkrypcja w procesie roboczym (kontrakt ``engine.transcribe``)."""
        cancel = should_cancel or (lambda: False)
        request = ("transcribe", str(audio_path), str(model_dir), model, language)
        with self._lock:
            if cancel():
                raise TranscriptionCancelled()
            try:
                return self._run(request, cancel, on_segment, on_progress)
            except _WorkerExited:
                # Proces mógł zakończyć się po bezczynności tuż przed
                # zleceniem — jedna ponowna próba w nowym procesie.
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
            try:
                conn.send(("stop",))
            except OSError:
                pass
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
        try:
            conn.send(request)
        except OSError as error:
            self._kill()
            raise _WorkerExited() from error
        received = False
        while True:
            if cancel():
                self._kill()
                raise TranscriptionCancelled()
            try:
                if not conn.poll(POLL_INTERVAL_S):
                    if not self.is_running():
                        raise EOFError
                    continue
                kind, payload = conn.recv()
            except (EOFError, OSError) as error:
                self._kill()
                if received:
                    raise _crash_error() from error
                raise _WorkerExited() from error
            received = True
            if kind == "segment":
                if on_segment is not None:
                    on_segment(payload)
            elif kind == "progress":
                if on_progress is not None:
                    on_progress(payload)
            elif kind == "done":
                result: TranscriptionResult = payload
                return result
            elif kind == "error":
                name, user_message, retry_hint = payload
                raise _ERRORS.get(name, TranscriptionError)(
                    user_message=user_message, retry_hint=retry_hint
                )

    def _ensure_started(self) -> Connection:
        if self._conn is not None and self.is_running():
            return self._conn
        self._kill()
        context = multiprocessing.get_context("spawn")
        parent_conn, child_conn = context.Pipe()
        process = context.Process(
            target=_serve,
            args=(
                child_conn,
                self._backend_factory,
                current_language(),
                self._idle_timeout_s,
            ),
            name="transkryptor-asr",
            daemon=True,
        )
        process.start()
        child_conn.close()
        self._process = process
        self._conn = parent_conn
        return parent_conn

    def _kill(self) -> None:
        conn, process = self._conn, self._process
        self._conn = None
        self._process = None
        _terminate(process, conn)


class _WorkerExited(Exception):
    """Proces roboczy zakończył się, zanim odpowiedział na zlecenie."""


def _crash_error() -> TranscriptionError:
    return TranscriptionError(
        user_message=tr("asr.error.worker_crashed"),
        retry_hint=tr("asr.error.transcribe.hint"),
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
) -> None:
    """Pętla procesu roboczego: zlecenia z potoku, bufor backendu."""
    set_language(language)
    cached: dict[Path, Backend] = {}
    factory = backend_factory or engine.faster_whisper_backend

    def cached_factory(model_dir: Path) -> Backend:
        backend = cached.get(model_dir)
        if backend is None:
            cached.clear()  # jeden model naraz — zwalnia poprzedni
            backend = factory(model_dir)
            cached[model_dir] = backend
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
            _, audio_path, model_dir, model, request_language = request
            conn.send(
                _transcribe_request(
                    conn, cached_factory, audio_path, model_dir, model, request_language
                )
            )


def _transcribe_request(
    conn: Connection,
    factory: Callable[[Path], Backend],
    audio_path: str,
    model_dir: str,
    model: AsrModelInfo,
    language: str,
) -> tuple[str, Any]:
    try:
        result = engine.transcribe(
            audio_path,
            model_dir,
            model=model,
            on_segment=lambda segment: conn.send(("segment", segment)),
            on_progress=lambda fraction: conn.send(("progress", fraction)),
            backend_factory=factory,
            language=language,
        )
    except AppError as error:
        return "error", (type(error).__name__, error.user_message, error.retry_hint)
    except Exception as error:  # noqa: BLE001 — błąd zgłaszany rodzicowi
        return "error", (
            "TranscriptionError",
            tr("asr.error.transcribe", reason=error),
            tr("asr.error.transcribe.hint"),
        )
    return "done", result


__all__ = ["AsrWorker"]
