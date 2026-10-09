"""PERF-03: suma SHA-256 nagrania liczona w tle, zapis projektu czeka na nią."""

import shutil
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from transkryptor.document.project import (
    AudioRef,
    ProjectState,
    file_sha256,
    load_project,
    save_project,
)
from transkryptor.ui.main_window import MainWindow

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")
SAMPLE_AAC = Path("tests/fixtures/audio/sample.aac")


@pytest.fixture
def window(add_window) -> MainWindow:
    return add_window(MainWindow())


@pytest.fixture
def audio(tmp_path) -> Path:
    target = tmp_path / "AdK_1954.mp3"
    shutil.copy(SAMPLE_MP3, target)
    return target


def accept_audio_change(monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def current_sha(window: MainWindow) -> str | None:
    audio = window.session._audio
    return audio.sha256 if audio is not None else None


def test_hash_is_computed_outside_ui_thread(qtbot, window, audio) -> None:
    threads: list[threading.Thread] = []

    def fake_hash(path, should_cancel=None) -> str:
        threads.append(threading.current_thread())
        return "suma"

    window.session.hash_impl = fake_hash
    window._on_import_audio(str(audio))
    qtbot.waitUntil(lambda: current_sha(window) == "suma", timeout=5000)
    assert threads and threads[0] is not threading.main_thread()


def test_real_hash_matches_file(qtbot, window, audio) -> None:
    window._on_import_audio(str(audio))
    expected = file_sha256(audio)
    qtbot.waitUntil(lambda: current_sha(window) == expected, timeout=10000)


def test_save_waits_for_pending_hash(
    qtbot, window, audio, tmp_path, monkeypatch
) -> None:
    release = threading.Event()

    def slow_hash(path, should_cancel=None) -> str:
        release.wait(10)
        return "policzona"

    window.session.hash_impl = slow_hash
    window._on_import_audio(str(audio))
    assert current_sha(window) == ""  # liczenie trwa
    target = tmp_path / "projekt.transkr"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )
    QTimer.singleShot(150, release.set)
    assert window.session.save_project()
    state = load_project(target)
    assert state.audio is not None
    assert state.audio.sha256 == "policzona"


def test_stale_hash_does_not_overwrite_new_recording(
    qtbot, window, audio, monkeypatch
) -> None:
    release_first = threading.Event()

    def fake_hash(path, should_cancel=None) -> str:
        if Path(path).name == audio.name:
            release_first.wait(10)  # ignoruje przerwanie — wynik i tak spóźniony
            return "stara"
        return "nowa"

    window.session.hash_impl = fake_hash
    window._on_import_audio(str(audio))
    accept_audio_change(monkeypatch)
    window._on_import_audio(str(SAMPLE_AAC))
    qtbot.waitUntil(lambda: current_sha(window) == "nowa", timeout=5000)
    release_first.set()
    qtbot.waitUntil(lambda: not window.session._hash_threads, timeout=5000)
    assert current_sha(window) == "nowa"
    assert window.session._audio is not None
    assert window.session._audio.absolute_path == str(SAMPLE_AAC.resolve())


def test_project_with_empty_hash_opens_without_question(
    qtbot, window, audio, tmp_path, no_blocking_dialogs
) -> None:
    project = tmp_path / "z_autozapisu.transkr"
    save_project(
        ProjectState(
            text="tekst",
            audio=AudioRef(absolute_path=str(audio), sha256=""),
        ),
        project,
    )
    assert window.session.open_project(project)
    assert window.player.source_path == audio
    assert not [call for call in no_blocking_dialogs if call[0] == "question"]


def test_open_project_reuses_verified_hash(qtbot, window, audio, tmp_path) -> None:
    project = tmp_path / "projekt.transkr"
    save_project(
        ProjectState(
            text="tekst",
            audio=AudioRef(absolute_path=str(audio), sha256=file_sha256(audio)),
        ),
        project,
    )
    calls: list[Path] = []

    def counting_hash(path, should_cancel=None) -> str:
        calls.append(Path(path))
        return file_sha256(path)

    window.session.hash_impl = counting_hash
    assert window.session.open_project(project)
    qtbot.waitUntil(lambda: not window.session._hash_threads, timeout=5000)
    assert len(calls) == 1  # tylko weryfikacja, bez drugiego liczenia
    assert current_sha(window) == file_sha256(audio)


def test_close_stops_hashing(qtbot, window, audio) -> None:
    started = threading.Event()

    def endless_hash(path, should_cancel=None) -> str:
        started.set()
        while not should_cancel():
            threading.Event().wait(0.01)
        raise InterruptedError(str(path))

    window.session.hash_impl = endless_hash
    window._on_import_audio(str(audio))
    assert started.wait(5)
    threads = list(window.session._hash_threads)
    assert window.session.can_close()
    assert all(thread.isFinished() for thread in threads)
