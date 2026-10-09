"""Testy integracyjne modułu audio na prawdziwych nagraniach (MP3, AAC).

Asercje dotyczą stanu odtwarzacza (ACC-08): załadowanie źródła, czas
trwania, prędkość i pozycja. Faktyczny dźwięk wymaga ręcznego smoke testu.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from transkryptor.audio.player import SUPPORTED_SUFFIXES, AudioPlayer
from transkryptor.errors import ImportAudioError

SAMPLE_MP3 = "tests/fixtures/audio/sample.mp3"
SAMPLE_AAC = "tests/fixtures/audio/sample.aac"


@pytest.fixture
def player(qapp):
    return AudioPlayer()


class TestLoad:
    def test_loads_real_mp3_and_reports_duration(self, player, qtbot) -> None:
        player.load(SAMPLE_MP3)
        assert player.source_path is not None
        assert player.source_path.name == "sample.mp3"
        with qtbot.waitSignal(player.duration_changed, timeout=10000) as blocker:
            pass
        assert blocker.args[0] > 0
        assert player.duration_ms > 0

    def test_loads_real_aac(self, player, qtbot) -> None:
        player.load(SAMPLE_AAC)
        with qtbot.waitSignal(player.duration_changed, timeout=10000) as blocker:
            pass
        assert blocker.args[0] > 0

    def test_rejects_unsupported_file(self, player, tmp_path) -> None:
        txt = tmp_path / "notatka.txt"
        txt.write_text("to nie audio")
        with pytest.raises(ImportAudioError, match="obsługiwanym") as exc_info:
            player.load(txt)
        assert "MP3" in exc_info.value.user_message
        assert "FLAC" in exc_info.value.user_message

    @pytest.mark.parametrize("suffix", [*SUPPORTED_SUFFIXES, ".WAV", ".Mp3"])
    def test_accepts_supported_suffixes(self, player, tmp_path, suffix) -> None:
        """Rozszerzenie przechodzi walidację; błąd dotyczy dopiero braku pliku."""
        with pytest.raises(ImportAudioError, match="Nie znaleziono"):
            player.load(tmp_path / f"brak{suffix}")

    def test_rejects_missing_file(self, player, tmp_path) -> None:
        with pytest.raises(ImportAudioError, match="Nie znaleziono"):
            player.load(tmp_path / "brak.mp3")

    def test_error_carries_user_message_and_retry_hint(self, player, tmp_path) -> None:
        with pytest.raises(ImportAudioError) as exc_info:
            player.load(tmp_path / "brak.mp3")
        assert exc_info.value.user_message
        assert exc_info.value.retry_hint


class TestPlayback:
    def test_play_pause_and_rate(self, player, qtbot) -> None:
        """ACC-08: odtwarzanie, pauza i zmiana prędkości zmieniają stan."""
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        player.set_rate(0.75)
        assert player.playback_rate == pytest.approx(0.75)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        qtbot.waitUntil(lambda: player.position_ms > 0, timeout=5000)
        player.pause()
        qtbot.waitUntil(lambda: not player.is_playing, timeout=5000)

    def test_set_position(self, player, qtbot) -> None:
        """ACC-08: przewijanie ustawia pozycję (po rozpoczęciu odtwarzania)."""
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.set_position(5000)
        qtbot.waitUntil(lambda: player.position_ms >= 4000, timeout=5000)

    def test_stop_and_unload(self, player, qtbot) -> None:
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        player.stop_and_unload()
        assert player.source_path is None


def _load(player: AudioPlayer, qtbot, path: str = SAMPLE_MP3) -> None:
    player.load(path)
    qtbot.waitUntil(lambda: player.duration_ms > 0, timeout=10000)


def _paused_at(player: AudioPlayer, qtbot, position_ms: int) -> None:
    """Odtwarza, pauzuje i ustawia pozycję — jak pauza w danym miejscu."""
    player.play()
    qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
    player.set_position(position_ms)
    qtbot.waitUntil(lambda: abs(player.position_ms - position_ms) < 400, timeout=5000)
    player.pause()
    qtbot.waitUntil(lambda: player.can_auto_rewind, timeout=5000)


class TestPositionBounds:
    def test_set_position_clamps_to_duration(self, player, qtbot) -> None:
        _load(player, qtbot)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.set_position(player.duration_ms + 60_000)
        qtbot.waitUntil(
            lambda: player.position_ms >= player.duration_ms - 1000
            or not player.is_playing,
            timeout=5000,
        )


class TestResume:
    def test_resume_rewinds(self, player, qtbot) -> None:
        """ACC-22: pauza na 10 s i wznowienie z cofnięciem 1,5 s → ok. 8,5 s."""
        _load(player, qtbot)
        _paused_at(player, qtbot, 10_000)
        paused = player.position_ms
        player.resume(1500)
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        qtbot.waitUntil(lambda: player.position_ms < paused - 1000, timeout=5000)
        assert player.position_ms == pytest.approx(paused - 1500, abs=600)

    def test_resume_near_start_goes_to_zero(self, player, qtbot) -> None:
        _load(player, qtbot)
        _paused_at(player, qtbot, 800)
        player.resume(1500)
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        assert player.position_ms < 700

    def test_can_auto_rewind_only_after_pause_without_seek(self, player, qtbot) -> None:
        _load(player, qtbot)
        assert not player.can_auto_rewind  # pierwszy start
        _paused_at(player, qtbot, 5000)
        assert player.can_auto_rewind
        player.set_position(20_000)  # suwak / skok w trakcie pauzy
        assert not player.can_auto_rewind


class TestLoop:
    def test_set_loop_validates_range(self, player, qtbot) -> None:
        _load(player, qtbot)
        with pytest.raises(ValueError):
            player.set_loop(5000, 5000)
        with pytest.raises(ValueError):
            player.set_loop(-1, 5000)
        with pytest.raises(ValueError):
            player.set_loop(0, player.duration_ms + 1)
        assert player.loop_range is None

    def test_set_and_clear_emit_loop_changed(self, player, qtbot) -> None:
        _load(player, qtbot)
        with qtbot.waitSignal(player.loop_changed) as blocker:
            player.set_loop(1000, 4000)
        assert blocker.args == [(1000, 4000)]
        assert player.loop_range == (1000, 4000)
        with qtbot.waitSignal(player.loop_changed) as blocker:
            player.clear_loop()
        assert blocker.args == [None]
        assert player.loop_range is None

    def test_position_past_end_jumps_to_start(self, player, qtbot) -> None:
        """Symulowane ``positionChanged`` za B wraca do A."""
        _load(player, qtbot)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.set_loop(2000, 6000)
        player._on_position_changed(6050)
        qtbot.waitUntil(lambda: player.position_ms < 4000, timeout=5000)

    def test_loop_returns_to_a_while_playing(self, player, qtbot) -> None:
        """ACC-21: odtwarzanie dochodzi do B i wraca do A."""
        _load(player, qtbot)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.set_loop(3000, 4000)
        player.set_position(3500)
        positions: list[int] = []
        player.position_changed.connect(positions.append)
        qtbot.waitUntil(
            lambda: any(p >= 3500 for p in positions) and positions[-1] < 3500,
            timeout=8000,
        )
        assert max(positions) <= 4000 + 150

    def test_load_and_unload_clear_loop(self, player, qtbot) -> None:
        _load(player, qtbot)
        player.set_loop(1000, 2000)
        _load(player, qtbot, SAMPLE_AAC)
        assert player.loop_range is None
        player.set_loop(1000, 2000)
        player.stop_and_unload()
        assert player.loop_range is None
