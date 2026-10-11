"""Fala dźwiękowa w oknie (faza 11, ACC-50)."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.ui import waveform as waveform_module
from transkryptor.ui.main_window import MainWindow

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


@pytest.fixture
def audio(tmp_path) -> Path:
    if not SAMPLE_MP3.is_file():
        pytest.skip(f"brak nagrania testowego {SAMPLE_MP3}")
    target = tmp_path / "nagranie.mp3"
    shutil.copy(SAMPLE_MP3, target)
    return target


def open_window(qtbot, add_window, audio: Path) -> MainWindow:
    window = add_window(MainWindow())
    window.resize(1100, 760)
    window.show()
    window._on_import_audio(str(audio))
    qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)
    qtbot.waitUntil(lambda: window.waveform.view.envelope is not None, timeout=20000)
    return window


def test_acc50_waveform_is_computed_cached_and_interactive(
    qtbot, add_window, audio, isolated_waveform_cache, monkeypatch
) -> None:
    window = open_window(qtbot, add_window, audio)
    view = window.waveform.view
    assert window.waveform.panel.isVisible()
    assert view.envelope is not None
    assert view.envelope.duration_ms == pytest.approx(90_000, abs=300)
    assert list(isolated_waveform_cache.glob("*.env"))

    # Ponowne otwarcie tego nagrania: obwiednia z cache, bez dekodowania.
    def no_decoding(*_args, **_kwargs):
        raise AssertionError("obwiednia powinna pochodzić z cache")

    monkeypatch.setattr(waveform_module, "compute_envelope", no_decoding)
    other = open_window(qtbot, add_window, audio)
    assert other.waveform.view.envelope == view.envelope

    # Klik przewija, przeciągnięcie ustawia pętlę A–B.
    seeks: list[int] = []
    monkeypatch.setattr(window.player, "set_position", seeks.append)
    x = view.width() // 4
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(x, 20))
    assert seeks == [view.ms_at(x)]

    start, end = view.width() // 2, view.width() // 2 + 120
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(start, 20))
    qtbot.mouseMove(view, QPoint(start + 30, 20))
    qtbot.mouseMove(view, QPoint(end, 20))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(end, 20))
    points = window.player_bar.loop_points()
    assert points == (view.ms_at(start), view.ms_at(end))
    assert window.player.loop_range == points
    assert view.loop == points


def test_overlays_zoom_and_collapse(qtbot, add_window, audio) -> None:
    window = open_window(qtbot, add_window, audio)
    view = window.waveform.view
    result = TranscriptionResult(
        text="a b",
        language="pl",
        segments=(
            SegmentResult(1.0, 2.0, " a", 0.9),
            SegmentResult(2.0, 3.0, " b", 0.2),
        ),
    )
    window.asr_panel.restore_result(result)
    assert view.segments == [(1000, 2000, 0.9), (2000, 3000, 0.2)]

    window.editor.setPlainText("tekst")
    window.sync.insert_timestamp()
    assert view.markers == [window.player.position_ms]

    full = view.visible_range_ms()
    view.zoom(0.1)
    zoomed = view.visible_range_ms()
    assert zoomed[1] - zoomed[0] < (full[1] - full[0]) / 5
    assert window.waveform.panel.scrollbar.isVisibleTo(window.waveform.panel)
    view.grab()  # rysowanie w obu stanach nie zgłasza błędów

    panel = window.waveform.panel
    panel.toggle.click()
    assert not view.isVisibleTo(panel)
    assert window.settings_store.current.player.waveform_visible is False
    window.settings_store.save(window.settings_store.current)
    assert not view.isVisibleTo(panel)


def test_waveform_hidden_without_recording(qtbot, add_window, audio) -> None:
    window = open_window(qtbot, add_window, audio)
    assert window.waveform.panel.isVisible()
    window.document.mark_exported()
    window._on_new_document()
    assert not window.waveform.panel.isVisible()
    assert window.waveform.view.envelope is None
