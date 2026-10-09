"""PERF-04: podproces roboczy ASR — bufor modelu, natychmiastowe anulowanie.

Fabryki backendu są funkcjami najwyższego poziomu: proces roboczy dostaje je
przez pickle. Ślad wywołań trafia do pliku wskazanego zmienną środowiskową
(proces ``spawn`` dziedziczy środowisko rodzica).
"""

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from transkryptor.asr.engine import (
    SegmentResult,
    TranscriptionCancelled,
    TranscriptionError,
)
from transkryptor.asr.models import REQUIRED_FILES
from transkryptor.asr.worker import AsrWorker
from transkryptor.errors import ModelDownloadError

LOG_ENV = "TRANSKRYPTOR_TEST_WORKER_LOG"


def _log(event: str) -> None:
    with open(os.environ[LOG_ENV], "a", encoding="utf-8") as handle:
        handle.write(f"{event}\n")


class _Backend:
    def __init__(self, prepare_s: float = 0.0, crash: bool = False) -> None:
        self._prepare_s = prepare_s
        self._crash = crash

    def transcribe(self, audio_path, language, vad_filter):
        _log("transcribe")
        if self._crash:
            os._exit(3)  # imitacja awarii natywnej (np. brak pamięci)
        time.sleep(self._prepare_s)  # dekodowanie i VAD przed 1. segmentem
        segments = [
            SimpleNamespace(start=0.0, end=1.0, text="Pierwsze.", avg_logprob=-0.1),
            SimpleNamespace(start=1.0, end=2.0, text=" Drugie.", avg_logprob=-0.2),
        ]
        return iter(segments), SimpleNamespace(language=language, duration=2.0)


def counting_factory(model_dir):
    _log("load")
    return _Backend()


def slow_factory(model_dir):
    _log("load")
    return _Backend(prepare_s=30.0)


def crashing_factory(model_dir):
    return _Backend(crash=True)


@pytest.fixture
def log_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "worker.log"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv(LOG_ENV, str(path))
    return path


@pytest.fixture
def model_dir(tmp_path) -> Path:
    directory = tmp_path / "models" / "medium"
    directory.mkdir(parents=True)
    for name in REQUIRED_FILES:
        (directory / name).write_bytes(b"fake")
    (directory / ".complete").write_text("fake", encoding="utf-8")
    return directory


@pytest.fixture
def audio(tmp_path) -> Path:
    path = tmp_path / "nagranie.mp3"
    path.write_bytes(b"fake-audio")
    return path


@pytest.fixture
def make_worker():
    workers: list[AsrWorker] = []

    def make(factory) -> AsrWorker:
        worker = AsrWorker(backend_factory=factory)
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.shutdown()


def events(log_file: Path) -> list[str]:
    return log_file.read_text(encoding="utf-8").split()


def test_model_is_loaded_once_for_two_transcriptions(
    log_file, model_dir, audio, make_worker
) -> None:
    worker = make_worker(counting_factory)
    segments: list[SegmentResult] = []
    progress: list[float] = []

    first = worker.transcribe(
        audio, model_dir, on_segment=segments.append, on_progress=progress.append
    )
    second = worker.transcribe(audio, model_dir)

    assert first.text == "Pierwsze. Drugie."
    assert second == first
    assert [segment.text for segment in segments] == ["Pierwsze.", " Drugie."]
    assert progress == [0.5, 1.0]
    assert events(log_file) == ["load", "transcribe", "transcribe"]


def test_cancel_before_first_segment_is_immediate(
    log_file, model_dir, audio, make_worker
) -> None:
    worker = make_worker(slow_factory)
    cancel = threading.Event()

    def request_cancel() -> None:
        # Anulowanie dopiero, gdy backend „przygotowuje” nagranie.
        deadline = time.monotonic() + 20
        while "transcribe" not in events(log_file) and time.monotonic() < deadline:
            time.sleep(0.02)
        cancel.set()

    threading.Thread(target=request_cancel, daemon=True).start()
    with pytest.raises(TranscriptionCancelled):
        worker.transcribe(audio, model_dir, should_cancel=cancel.is_set)
    cancelled_at = time.monotonic()
    assert not worker.is_running()
    assert "transcribe" in events(log_file)
    # Zakończenie procesu, nie czekanie na 30 s przygotowania.
    assert time.monotonic() - cancelled_at < 3


def test_next_transcription_after_cancel_starts_new_process(
    log_file, model_dir, audio, make_worker
) -> None:
    worker = make_worker(counting_factory)
    with pytest.raises(TranscriptionCancelled):
        worker.transcribe(audio, model_dir, should_cancel=lambda: True)
    result = worker.transcribe(audio, model_dir)
    assert result.text == "Pierwsze. Drugie."


def test_crashed_process_reports_transcription_error(
    log_file, model_dir, audio, make_worker
) -> None:
    worker = make_worker(crashing_factory)
    with pytest.raises(TranscriptionError) as exc_info:
        worker.transcribe(audio, model_dir)
    assert "nieoczekiwanie" in exc_info.value.user_message
    assert exc_info.value.retry_hint
    assert not worker.is_running()


def test_missing_model_error_is_passed_through(
    log_file, tmp_path, audio, make_worker
) -> None:
    worker = make_worker(counting_factory)
    with pytest.raises(ModelDownloadError) as exc_info:
        worker.transcribe(audio, tmp_path / "brak-modelu")
    assert "nie został jeszcze pobrany" in exc_info.value.user_message
    assert exc_info.value.retry_hint
    assert worker.is_running()  # błąd zlecenia nie kończy procesu


def test_idle_worker_exits_and_restarts(log_file, model_dir, audio) -> None:
    worker = AsrWorker(backend_factory=counting_factory, idle_timeout_s=0.3)
    try:
        worker.transcribe(audio, model_dir)
        deadline = time.monotonic() + 10
        while worker.is_running() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not worker.is_running()  # pamięć zwolniona po bezczynności
        assert worker.transcribe(audio, model_dir).text == "Pierwsze. Drugie."
        assert events(log_file).count("load") == 2
    finally:
        worker.shutdown()


def test_ping_and_shutdown(make_worker) -> None:
    worker = make_worker(None)
    assert worker.ping()
    assert worker.is_running()
    worker.shutdown()
    assert not worker.is_running()
