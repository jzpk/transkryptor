"""Testy paska odtwarzacza (ACC-08 na poziomie UI)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from transkryptor.audio.player import AudioPlayer
from transkryptor.ui.player_bar import PLAYBACK_RATES, PlayerBar, format_ms

SAMPLE_MP3 = "tests/fixtures/audio/sample.mp3"


@pytest.fixture
def player_bar(qtbot):
    player = AudioPlayer()
    bar = PlayerBar(player)
    qtbot.addWidget(bar)
    yield bar, player
    # Zniszczenie QMediaPlayer w trakcie odtwarzania wywraca wątek dekodera
    # FFmpeg (segfault w CI) — najpierw zatrzymanie i zwolnienie źródła.
    player.stop_and_unload()


def test_format_ms() -> None:
    assert format_ms(0) == "00:00"
    assert format_ms(65_000) == "01:05"
    assert format_ms(600_000) == "10:00"


class TestPlayerBar:
    def test_initial_state_is_empty(self, player_bar) -> None:
        bar, _player = player_bar
        assert not bar.play_button.isEnabled()
        assert bar.time_label.text() == "00:00 / 00:00"
        assert bar.rate_combo.currentText() == "1x"

    def test_rate_combo_changes_playback_rate(self, player_bar) -> None:
        bar, player = player_bar
        bar.rate_combo.setCurrentIndex(1)  # 0.75x
        assert player.playback_rate == pytest.approx(PLAYBACK_RATES[1][1])

    def test_loading_mp3_enables_controls(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        qtbot.waitUntil(lambda: bar.play_button.isEnabled(), timeout=5000)
        assert bar.rate_combo.isEnabled()
        assert bar.position_slider.isEnabled()
        assert bar.position_slider.maximum() > 0

    def test_play_toggles_button_label(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        qtbot.waitUntil(lambda: bar.play_button.isEnabled(), timeout=5000)
        bar.play_button.click()
        qtbot.waitUntil(lambda: bar.play_button.text() == "Pauza", timeout=5000)
        bar.play_button.click()
        qtbot.waitUntil(lambda: bar.play_button.text() == "Odtwórz", timeout=5000)

    def test_position_updates_time_label(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.set_position(65_000)
        qtbot.waitUntil(lambda: bar.time_label.text().startswith("01:0"), timeout=5000)

    def test_reset_restores_empty_state(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        qtbot.waitSignal(player.duration_changed, timeout=10000)
        player.stop_and_unload()
        bar.reset()
        assert not bar.play_button.isEnabled()
        assert bar.time_label.text() == "00:00 / 00:00"


# --- faza 06: skróty, auto-cofanie, pętla ------------------------------------

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402

from transkryptor.settings import PlayerSettings, Settings  # noqa: E402
from transkryptor.ui.main_window import MainWindow  # noqa: E402
from transkryptor.ui.player_bar import format_loop  # noqa: E402
from transkryptor.ui.shortcuts import PLAYER_ACTIONS  # noqa: E402

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier


def _wait_media(qtbot, bar: PlayerBar) -> None:
    qtbot.waitUntil(lambda: bar.has_media, timeout=10000)


@pytest.fixture
def window(qtbot, add_window):
    """Okno z nagraniem i fokusem w edytorze (jak przy pisaniu)."""
    win = add_window(MainWindow())
    win.show()
    qtbot.waitExposed(win)
    win.activateWindow()
    win._on_import_audio(SAMPLE_MP3)
    _wait_media(qtbot, win.player_bar)
    win.editor.setFocus()
    return win


def test_format_loop() -> None:
    assert format_loop(None, None) == ""
    assert format_loop(72_000, None) == "A 01:12"
    assert format_loop(72_000, 78_000) == "A 01:12 – B 01:18"


def test_player_actions_do_not_collide_with_editor_shortcuts() -> None:
    from transkryptor.ui.markers import MARKERS, SUPERSCRIPT_SHORTCUT

    taken = {m.shortcut for m in MARKERS} | {
        SUPERSCRIPT_SHORTCUT,
        "Ctrl+Left",
        "Ctrl+Right",
        "Ctrl+N",
        "Ctrl+E",
        "Ctrl+W",
    }
    player = [s for action in PLAYER_ACTIONS for s in action.shortcuts]
    assert len(player) == len(set(player))
    normalized = {QKeySequence(s).toString() for s in taken}
    assert not normalized & {QKeySequence(s).toString() for s in player}


class TestShortcutsFromEditor:
    """ACC-19: skróty działają z fokusem w edytorze i nie zmieniają tekstu."""

    def test_play_pause_shortcuts(self, qtbot, window) -> None:
        undo_steps = window.editor.document().availableUndoSteps()
        qtbot.keyClick(window.editor, Qt.Key.Key_Space, CTRL)
        qtbot.waitUntil(lambda: window.player.is_playing, timeout=5000)
        qtbot.keyClick(window.editor, Qt.Key.Key_F4)
        qtbot.waitUntil(lambda: not window.player.is_playing, timeout=5000)
        assert window.editor.toPlainText() == ""
        assert window.editor.document().availableUndoSteps() == undo_steps

    def test_skip_uses_settings(self, qtbot, window) -> None:
        window.player.play()
        qtbot.waitUntil(lambda: window.player.is_playing, timeout=5000)
        window.player.set_position(20_000)
        qtbot.waitUntil(lambda: window.player.position_ms >= 19_500, timeout=5000)
        window.player.pause()
        qtbot.waitUntil(lambda: not window.player.is_playing, timeout=5000)
        start = window.player.position_ms
        qtbot.keyClick(window.editor, Qt.Key.Key_Left, ALT)
        qtbot.waitUntil(
            lambda: abs(window.player.position_ms - (start - 3000)) < 300, timeout=5000
        )
        window.settings_store.save(Settings(player=PlayerSettings(skip_ms=5000)))
        qtbot.keyClick(window.editor, Qt.Key.Key_Right, ALT)
        qtbot.waitUntil(
            lambda: abs(window.player.position_ms - (start + 2000)) < 300, timeout=5000
        )
        assert window.editor.toPlainText() == ""

    def test_skip_back_clamps_to_zero(self, qtbot, window) -> None:
        qtbot.keyClick(window.editor, Qt.Key.Key_Left, ALT)
        assert window.player.position_ms == 0

    def test_rate_shortcuts_update_combo(self, qtbot, window) -> None:
        undo_steps = window.editor.document().availableUndoSteps()
        qtbot.keyClick(window.editor, Qt.Key.Key_Period, CTRL | SHIFT)
        assert window.player_bar.rate_combo.currentText() == "1.25x"
        assert window.player.playback_rate == pytest.approx(1.25)
        for _ in range(10):
            qtbot.keyClick(window.editor, Qt.Key.Key_Comma, CTRL | SHIFT)
        assert window.player_bar.rate_combo.currentText() == PLAYBACK_RATES[0][0]
        assert window.editor.toPlainText() == ""
        assert window.editor.document().availableUndoSteps() == undo_steps

    def test_actions_disabled_without_media(self, add_window) -> None:
        win = add_window(MainWindow())
        assert not any(a.isEnabled() for a in win.player_actions.values())

    def test_actions_disabled_during_asr(self, qtbot, window) -> None:
        window._set_ui_locked(True)
        assert not any(a.isEnabled() for a in window.player_actions.values())
        qtbot.keyClick(window.editor, Qt.Key.Key_F4)
        assert not window.player.is_playing
        window._set_ui_locked(False)
        assert all(a.isEnabled() for a in window.player_actions.values())

    def test_actions_disabled_after_new_document(self, window) -> None:
        window._on_new_document()
        assert not any(a.isEnabled() for a in window.player_actions.values())

    def test_play_button_tooltip_shows_shortcuts(self, window) -> None:
        tooltip = window.player_bar.play_button.toolTip()
        assert "F4" in tooltip


class TestAutoRewind:
    """ACC-22: wznowienie po pauzie cofa nagranie zgodnie z ustawieniami."""

    def _pause_at(self, qtbot, bar: PlayerBar, player, position_ms: int) -> None:
        bar.toggle_play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.set_position(position_ms)
        qtbot.waitUntil(
            lambda: abs(player.position_ms - position_ms) < 400, timeout=5000
        )
        bar.toggle_play()
        qtbot.waitUntil(lambda: player.can_auto_rewind, timeout=5000)

    def test_default_rewinds_1500_ms(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        _wait_media(qtbot, bar)
        self._pause_at(qtbot, bar, player, 10_000)
        paused = player.position_ms
        bar.toggle_play()
        qtbot.waitUntil(lambda: player.position_ms < paused - 1000, timeout=5000)
        assert player.position_ms == pytest.approx(paused - 1500, abs=600)

    def test_disabled_in_settings(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        bar.apply_settings(PlayerSettings(auto_rewind_enabled=False))
        player.load(SAMPLE_MP3)
        _wait_media(qtbot, bar)
        self._pause_at(qtbot, bar, player, 10_000)
        paused = player.position_ms
        bar.toggle_play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        assert player.position_ms >= paused - 100

    def test_no_rewind_on_first_start(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        _wait_media(qtbot, bar)
        assert not player.can_auto_rewind
        bar.toggle_play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)

    def test_near_start_rewinds_to_zero(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        player.load(SAMPLE_MP3)
        _wait_media(qtbot, bar)
        self._pause_at(qtbot, bar, player, 700)
        bar.toggle_play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        assert player.position_ms < 600


class TestLoopControls:
    """ACC-21: znaczniki A–B, przełącznik pętli i etykieta zakresu."""

    def _at(self, qtbot, player, position_ms: int) -> None:
        player.set_position(position_ms)
        qtbot.waitUntil(
            lambda: abs(player.position_ms - position_ms) < 300, timeout=5000
        )

    def _ready(self, qtbot, bar, player) -> None:
        player.load(SAMPLE_MP3)
        _wait_media(qtbot, bar)
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        player.pause()

    def test_controls_disabled_without_media(self, player_bar) -> None:
        bar, _player = player_bar
        assert not bar.loop_a_button.isEnabled()
        assert not bar.loop_button.isEnabled()

    def test_mark_a_b_and_toggle(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        self._ready(qtbot, bar, player)
        self._at(qtbot, player, 72_000)
        bar.mark_a()
        assert bar.loop_button.isEnabled()
        self._at(qtbot, player, 78_000)
        bar.mark_b()
        assert bar.loop_label.text().startswith("A 01:1")
        assert "B 01:1" in bar.loop_label.text()
        bar.toggle_loop()
        assert bar.loop_button.isChecked()
        start, end = player.loop_range
        assert 71_500 < start < 72_500 and 77_500 < end < 78_500
        bar.toggle_loop()
        assert player.loop_range is None
        assert not bar.loop_button.isChecked()
        assert bar.loop_label.text() == ""

    def test_b_without_a_starts_at_zero(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        self._ready(qtbot, bar, player)
        self._at(qtbot, player, 5000)
        bar.mark_b()
        bar.toggle_loop()
        assert player.loop_range is not None
        assert player.loop_range[0] == 0

    def test_b_before_a_is_rejected(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        self._ready(qtbot, bar, player)
        self._at(qtbot, player, 10_000)
        bar.mark_a()
        self._at(qtbot, player, 5000)
        bar.mark_b()
        assert "B" not in bar.loop_label.text()

    def test_a_only_loops_to_end(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        self._ready(qtbot, bar, player)
        self._at(qtbot, player, 10_000)
        bar.mark_a()
        bar.toggle_loop()
        assert player.loop_range is not None
        assert player.loop_range[1] == player.duration_ms

    def test_reset_clears_markers(self, qtbot, player_bar) -> None:
        bar, player = player_bar
        self._ready(qtbot, bar, player)
        self._at(qtbot, player, 10_000)
        bar.mark_a()
        bar.toggle_loop()
        player.stop_and_unload()
        bar.reset()
        assert bar.loop_label.text() == ""
        assert not bar.loop_button.isChecked()
        assert not bar.loop_button.isEnabled()

    def test_loop_shortcuts_from_editor(self, qtbot, window) -> None:
        player = window.player
        player.play()
        qtbot.waitUntil(lambda: player.is_playing, timeout=5000)
        self._at(qtbot, player, 3000)
        qtbot.keyClick(window.editor, Qt.Key.Key_A, CTRL | SHIFT)
        self._at(qtbot, player, 6000)
        qtbot.keyClick(window.editor, Qt.Key.Key_B, CTRL | SHIFT)
        qtbot.keyClick(window.editor, Qt.Key.Key_L, CTRL | SHIFT)
        assert player.loop_range is not None
        assert window.editor.toPlainText() == ""
        qtbot.keyClick(window.editor, Qt.Key.Key_L, CTRL | SHIFT)
        assert player.loop_range is None
