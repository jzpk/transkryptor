"""Blokada uśpienia i wygaszacza na czas transkrypcji (zgłoszenie #68)."""

import pytest

from transkryptor.ui.keep_awake import KeepAwake
from transkryptor.ui.main_window import MainWindow


class FakeBackend:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def acquire(self, reason: str) -> bool:
        self.calls.append(f"acquire:{reason}")
        if self.fail:
            raise OSError("brak usługi")
        return True

    def release(self) -> None:
        self.calls.append("release")


def test_hold_and_release_once() -> None:
    backend = FakeBackend()
    awake = KeepAwake(backend)
    awake.hold("praca")
    awake.hold("praca")
    assert awake.held
    awake.release()
    awake.release()
    assert not awake.held
    assert backend.calls == ["acquire:praca", "release"]


def test_backend_error_does_not_break_work() -> None:
    awake = KeepAwake(FakeBackend(fail=True))
    awake.hold("praca")
    awake.release()
    assert not awake.held


@pytest.fixture
def window(add_window) -> MainWindow:
    return add_window(MainWindow())


def test_transcription_keeps_computer_awake(window) -> None:
    window.asr.transcription_started()
    assert window.asr.keep_awake.held
    window.asr.transcription_finished()
    assert not window.asr.keep_awake.held
