"""Mapa pokrycia transkrypcji na fali, przejścia do luk i spektrogram."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.document.project import ProjectState
from transkryptor.settings import PlayerSettings, Settings
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.shortcuts import NEXT_GAP_ID, PREVIOUS_GAP_ID
from transkryptor.ui.spectrogram_view import palette
from transkryptor.ui.theme import DARK, LIGHT
from transkryptor.ui.time_selection import LOOP, SEEK, DragSelection

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")
TEXT = "pierwszy fragment\ndrugi fragment"


@pytest.fixture
def window(qtbot, add_window, tmp_path) -> MainWindow:
    """Okno z nagraniem (90 s) i tekstem powiązanym z 0-20 s i 50-60 s."""
    if not SAMPLE_MP3.is_file():
        pytest.skip(f"brak nagrania testowego {SAMPLE_MP3}")
    audio = tmp_path / "nagranie.mp3"
    shutil.copy(SAMPLE_MP3, audio)
    win = add_window(MainWindow())
    win.resize(1100, 760)
    win.show()
    state = ProjectState(
        text=TEXT,
        anchors=(
            Anchor(0, 17, 0, 20_000, SEGMENT),
            Anchor(18, 32, 50_000, 60_000, SEGMENT),
        ),
    )
    win.session.apply_state(state, None, audio, saved=True)
    qtbot.waitUntil(lambda: win.player_bar.has_media, timeout=10000)
    qtbot.waitUntil(lambda: win.waveform.view.envelope is not None, timeout=20000)
    win.coverage.refresh()
    return win


def test_coverage_map_shows_gaps_and_percent(window) -> None:
    coverage = window.coverage
    # Nagranie testowe: dźwięk do końca, bez długiej ciszy w lukach.
    assert coverage.gaps[0][0] == 20_000
    assert coverage.gaps[-1][1] == pytest.approx(90_000, abs=300)
    assert window.waveform.view.covered == [(0, 20_000), (50_000, 60_000)]
    assert window.waveform.panel.overview.gaps == list(coverage.gaps)
    label = window.waveform.panel.coverage_label.text()
    assert label.startswith("Pokrycie: 33%")
    assert f"luki: {len(coverage.gaps)}" in label


def test_gap_navigation_moves_playback_and_cursor(window, qtbot) -> None:
    assert window.coverage.next_action.isEnabled()
    window.player.set_position(1000)
    window.coverage.next_action.trigger()
    qtbot.waitUntil(lambda: window.player.position_ms >= 19_000, timeout=5000)
    assert window.player.position_ms == pytest.approx(20_000, abs=100)
    first_gap = window.coverage.gaps[0][0]
    window.coverage.previous_action.trigger()
    assert "Luka" in window.statusBar().currentMessage()
    assert window.coverage.go_to(forward=True)
    assert first_gap == 20_000


def test_gap_shortcuts_are_configurable(window) -> None:
    shortcuts = window.shortcut_actions
    assert shortcuts[NEXT_GAP_ID] is window.coverage.next_action
    assert shortcuts[PREVIOUS_GAP_ID] is window.coverage.previous_action
    assert window.coverage.next_action.shortcut().toString() == "F6"


def test_editing_refreshes_the_map(window, qtbot) -> None:
    window.sync.clear()  # tekst bez kotwic - całe nagranie to luka
    qtbot.waitUntil(lambda: window.waveform.view.covered == [], timeout=3000)
    assert window.waveform.panel.coverage_label.text().startswith("Pokrycie: 0%")


def test_stats_show_the_same_gaps(window) -> None:
    stats = window.progress.stats()
    assert stats.gaps == window.coverage.gaps


def test_spectrogram_for_loop_and_too_long_range(window, qtbot) -> None:
    panel = window.waveform.panel.spectrogram
    controller = window.waveform.spectrogram
    panel.set_expanded(True)
    # Bez pętli i bez powiększenia - całe nagranie jest za długie.
    controller.refresh()
    assert panel.view.spectrogram is None
    assert "15 s" in panel.status_label.text()

    window.player_bar.set_loop_points(10_000, 12_000)
    window.waveform.refresh_loop()
    controller.refresh()
    qtbot.waitUntil(lambda: panel.view.spectrogram is not None, timeout=15000)
    spectrogram = panel.view.spectrogram
    assert spectrogram is not None
    assert spectrogram.start_ms == 10_000
    assert spectrogram.end_ms == pytest.approx(12_000, abs=20)
    assert panel.status_label.text() == ""
    assert panel.view.image() is not None

    # Klik w spektrogram przewija nagranie w jego zakresie.
    view = panel.view
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(view.width() // 2, 20))
    qtbot.waitUntil(lambda: abs(window.player.position_ms - 11_000) < 300, timeout=5000)


def test_spectrogram_follows_zoomed_waveform(window, qtbot) -> None:
    panel = window.waveform.panel.spectrogram
    panel.set_expanded(True)
    view = window.waveform.view
    view.zoom(0.1)  # ok. 9 s widocznej fali
    start, end = view.visible_range_ms()
    assert end - start <= 15_000
    window.waveform.spectrogram.refresh()
    qtbot.waitUntil(lambda: panel.view.spectrogram is not None, timeout=15000)
    assert panel.view.spectrogram.start_ms == int(start)


def test_collapsed_spectrogram_computes_nothing(window) -> None:
    window.player_bar.set_loop_points(10_000, 12_000)
    window.waveform.refresh_loop()
    window.waveform.spectrogram.refresh()
    assert not window.waveform.spectrogram.is_busy


def test_spectrogram_state_and_options_are_saved(window) -> None:
    window.waveform.panel.spectrogram.set_expanded(True)
    assert window.settings_store.current.player.spectrogram_visible
    options = window.settings_store.current.player.spectrogram
    assert window.waveform.spectrogram.options == options


def test_spectrogram_settings_round_trip(qtbot) -> None:
    settings = Settings(
        player=PlayerSettings(spectrogram_max_hz=8000, spectrogram_window="narrowband")
    )
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    page = dialog.player_page
    assert page.spectrogram_range_combo.currentData() == 8000
    assert page.spectrogram_window_combo.currentData() == "narrowband"
    page.spectrogram_range_combo.setCurrentIndex(0)
    assert dialog.settings().player.spectrogram_max_hz == 5000


def test_palette_follows_theme() -> None:
    light = palette(LIGHT)
    dark = palette(DARK)
    assert len(light) == len(dark) == 256
    # Jasny motyw: duża energia ciemna; ciemny motyw: jasna.
    assert light[-1] != dark[-1]
    assert light[0] != dark[0]


def test_drag_selection() -> None:
    drag = DragSelection(lambda x: int(x * 10))
    drag.press(10)
    assert drag.release() == (SEEK, 100, 100)
    drag.press(10)
    drag.move(12)  # w granicy kliknięcia
    assert drag.selection() is None
    drag.move(40)
    assert drag.selection() == (100, 400)
    assert drag.release() == (LOOP, 100, 400)
    assert drag.release() is None
