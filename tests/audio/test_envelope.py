"""Obwiednia nagrania dla fali dźwiękowej (faza 11, ACC-50)."""

from pathlib import Path

import pytest

from transkryptor.audio.envelope import (
    STEP_MS,
    Envelope,
    compute_envelope,
    load_cached,
    save_cached,
)

SAMPLES = [
    Path("tests/fixtures/audio/sample.mp3"),
    Path("tests/fixtures/audio/sample.aac"),
]


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.suffix)
def test_envelope_covers_recording(path: Path) -> None:
    progress: list[float] = []
    envelope = compute_envelope(path, on_progress=progress.append)
    assert envelope.step_ms == STEP_MS
    # Nagrania testowe trwają ok. 90 s.
    assert envelope.duration_ms == pytest.approx(90_000, abs=300)
    assert max(envelope.peaks) > 0
    assert progress and progress == sorted(progress) and progress[-1] <= 1.0


def test_cancel_interrupts_decoding() -> None:
    with pytest.raises(InterruptedError):
        compute_envelope(SAMPLES[0], should_cancel=lambda: True)


def test_missing_file_raises() -> None:
    with pytest.raises(Exception):  # noqa: B017 - OSError albo błąd PyAV
        compute_envelope("brak.mp3")


class TestCache:
    def test_round_trip(self, tmp_path: Path) -> None:
        envelope = Envelope(10, bytes([0, 5, 255, 17]))
        assert save_cached("abc", envelope, tmp_path)
        assert load_cached("abc", tmp_path) == envelope
        assert load_cached("inna", tmp_path) is None
        assert load_cached("", tmp_path) is None

    @pytest.mark.parametrize(
        "payload", [b"", b"TKENV", b"XXXXX\x01\x0a\x00\x02\x00\x00\x00ab", b"x" * 40]
    )
    def test_damaged_file_is_ignored(self, tmp_path: Path, payload: bytes) -> None:
        (tmp_path / "abc.env").write_bytes(payload)
        assert load_cached("abc", tmp_path) is None

    def test_truncated_file_is_ignored(self, tmp_path: Path) -> None:
        save_cached("abc", Envelope(10, bytes(100)), tmp_path)
        path = tmp_path / "abc.env"
        path.write_bytes(path.read_bytes()[:-1])
        assert load_cached("abc", tmp_path) is None

    def test_unwritable_directory_does_not_raise(self, tmp_path: Path) -> None:
        blocker = tmp_path / "plik"
        blocker.write_text("nie katalog")
        assert not save_cached("abc", Envelope(10, b"\x01"), blocker / "sub")
