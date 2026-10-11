"""Tekst powiązany z nagraniem w oknie (faza 11: ACC-45, ACC-46, ACC-48)."""

import shutil
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.document.anchors import MANUAL, SEGMENT
from transkryptor.ui.highlights import ACTIVE_LAYER
from transkryptor.ui.main_window import MainWindow

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")

SENTENCES = (
    (0.0, 2.0, " Pierwsze zdanie."),
    (2.0, 4.0, " Drugie zdanie."),
    (4.0, 6.5, " Trzecie zdanie."),
    (6.5, 9.0, " Czwarte zdanie."),
)


def draft_result(segments=SENTENCES) -> TranscriptionResult:
    results = tuple(SegmentResult(s, e, text, 0.9) for s, e, text in segments)
    return TranscriptionResult(
        text="".join(r.text for r in results).strip(), language="pl", segments=results
    )


@pytest.fixture
def audio(tmp_path) -> Path:
    if not SAMPLE_MP3.is_file():
        pytest.skip(f"brak nagrania testowego {SAMPLE_MP3}")
    target = tmp_path / "nagranie.mp3"
    shutil.copy(SAMPLE_MP3, target)
    return target


@pytest.fixture
def window(qtbot, add_window, audio) -> MainWindow:
    win = add_window(MainWindow())
    win.resize(1000, 700)
    win.show()
    win._on_import_audio(str(audio))
    qtbot.waitUntil(lambda: win.player_bar.has_media, timeout=10000)
    return win


@pytest.fixture
def playback(window, monkeypatch) -> list[tuple[str, int]]:
    """Zlecenia odtwarzacza zamiast prawdziwego odtwarzania."""
    calls: list[tuple[str, int]] = []
    player = window.player
    monkeypatch.setattr(player, "set_position", lambda ms: calls.append(("seek", ms)))
    monkeypatch.setattr(player, "play", lambda: calls.append(("play", 0)))
    monkeypatch.setattr(
        player,
        "play_loop_once",
        lambda start, end: calls.extend([("loop", start), ("to", end)]),
    )
    return calls


def ctrl_click(qtbot, window: MainWindow, position: int) -> None:
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(position)
    point = window.editor.cursorRect(cursor).center()
    qtbot.mouseClick(
        window.editor.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        point,
    )


def segment_texts(window: MainWindow) -> list[str]:
    text = window.editor.plain_text()
    return [text[a.start : a.end] for a in window.sync.entries() if a.source == SEGMENT]


class TestPlaybackFromText:
    def test_acc45_ctrl_click_and_active_segment(self, qtbot, window, playback) -> None:
        window._on_draft_ready(draft_result())
        assert segment_texts(window) == [s[2].strip() for s in SENTENCES]
        text = window.editor.plain_text()
        third = text.index("Trzecie") + 3
        ctrl_click(qtbot, window, third)
        preroll = window.settings_store.current.player.segment_preroll_ms
        assert playback == [("seek", 4000 - preroll), ("play", 0)]

        window.player.position_changed.emit(500)
        layer = window.editor.highlight_layer(ACTIVE_LAYER)
        assert [s.cursor.selectedText() for s in layer] == ["Pierwsze zdanie."]
        qtbot.wait(200)  # przerwa dłuższa niż ograniczenie częstotliwości
        window.player.position_changed.emit(7000)
        qtbot.waitUntil(
            lambda: [
                s.cursor.selectedText()
                for s in window.editor.highlight_layer(ACTIVE_LAYER)
            ]
            == ["Czwarte zdanie."],
            timeout=2000,
        )

    def test_play_from_cursor_shortcut_uses_segment(self, window, playback) -> None:
        window._on_draft_ready(draft_result())
        cursor = window.editor.textCursor()
        cursor.setPosition(window.editor.plain_text().index("Drugie") + 2)
        window.editor.setTextCursor(cursor)
        window.player_actions["play_from_cursor"].trigger()
        preroll = window.settings_store.current.player.segment_preroll_ms
        assert playback[0] == ("seek", 2000 - preroll)

    def test_text_without_anchor_reports_status(self, qtbot, window, playback) -> None:
        window.editor.setPlainText("Tekst wpisany ręcznie.")
        ctrl_click(qtbot, window, 3)
        assert playback == []
        assert "nie jest powiązane" in window.statusBar().currentMessage()


class TestAnchorsSurviveEditing:
    def test_acc46_delete_segment_edit_another_and_reopen(
        self, qtbot, window, add_window, tmp_path, monkeypatch
    ) -> None:
        window._on_draft_ready(draft_result())
        editor = window.editor
        text = editor.plain_text()
        # Usunięcie całego drugiego segmentu (ze spacją przed nim).
        cursor = QTextCursor(editor.document())
        start = text.index(" Drugie")
        cursor.setPosition(start)
        cursor.setPosition(
            start + len(" Drugie zdanie."), QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        # Dopisanie tekstu w środku trzeciego segmentu.
        cursor.setPosition(editor.plain_text().index("zdanie", 20))
        cursor.insertText("bardzo ")
        expected = ["Pierwsze zdanie.", "Trzecie bardzo zdanie.", "Czwarte zdanie."]
        assert segment_texts(window) == expected

        path = tmp_path / "projekt.transkr"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(path), "")),
        )
        assert window.session.save_project()
        reopened = add_window(MainWindow())
        assert reopened.session.open_project(path)
        assert segment_texts(reopened) == expected
        times = [
            (a.start_ms, a.end_ms)
            for a in reopened.sync.entries()
            if a.source == SEGMENT
        ]
        assert times == [(0, 2000), (4000, 6500), (6500, 9000)]

    def test_replace_draft_drops_old_anchors(self, window, monkeypatch) -> None:
        window._on_draft_ready(draft_result())
        monkeypatch.setattr(window, "_ask_draft_placement", lambda: "replace")
        window._on_draft_ready(draft_result(SENTENCES[:1]))
        assert segment_texts(window) == ["Pierwsze zdanie."]

    def test_append_draft_keeps_offsets(self, window, monkeypatch) -> None:
        window._on_draft_ready(draft_result(SENTENCES[:2]))
        monkeypatch.setattr(window, "_ask_draft_placement", lambda: "append")
        window._on_draft_ready(draft_result(SENTENCES[2:]))
        assert segment_texts(window) == [s[2].strip() for s in SENTENCES]

    def test_rule_at_segment_end_stays_in_segment(self, window) -> None:
        for code, box in window.asr_panel.rule_checkboxes.items():
            box.setChecked(code == "SUG-NAS-A-FINAL")
        window._on_draft_ready(
            draft_result(((0.0, 1.0, " oni są"), (1.0, 2.0, " i już")))
        )
        assert window.editor.plain_text() == "[00:00] oni som i już"
        assert segment_texts(window) == ["oni som", "i już"]
        cursor = QTextCursor(window.editor.document())
        cursor.setPosition(len("[00:00] oni som"))
        cursor.insertText(" no")
        assert segment_texts(window) == ["oni som", "i już"]


class TestManualTimestamps:
    def test_acc48_timestamp_plays_from_saved_time_and_is_not_exported(
        self, qtbot, window, tmp_path, monkeypatch
    ) -> None:
        editor = window.editor
        editor.setPlainText("Pierwszy akapit tekstu. Drugi fragment.")
        window.document.mark_exported()
        cursor = editor.textCursor()
        marker_at = editor.plain_text().index("Drugi")
        cursor.setPosition(marker_at)
        editor.setTextCursor(cursor)
        monkeypatch.setattr(
            type(window.player), "position_ms", property(lambda _: 12345)
        )
        window.player_actions["insert_timestamp"].trigger()
        assert [(a.start, a.start_ms, a.source) for a in window.sync.entries()] == [
            (marker_at, 12345, MANUAL)
        ]
        # Znacznik to dane projektu, nie tekst eksportu.
        assert window.document.is_unsaved
        assert not window.document.is_dirty

        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            window.player, "set_position", lambda ms: calls.append(("seek", ms))
        )
        monkeypatch.setattr(window.player, "play", lambda: calls.append(("play", 0)))
        ctrl_click(qtbot, window, marker_at + 4)
        assert calls == [("seek", 12345), ("play", 0)]

        target = tmp_path / "eksport.docx"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")),
        )
        window._on_export()
        paragraphs = [p.text for p in DocxDocument(str(target)).paragraphs]
        # Decyzja fazy 11: znaczniki niewidoczne w DOCX.
        assert paragraphs[-1] == "Pierwszy akapit tekstu. Drugi fragment."

    def test_timestamp_moves_with_text_and_can_be_removed(self, window) -> None:
        editor = window.editor
        editor.setPlainText("abc def")
        cursor = editor.textCursor()
        cursor.setPosition(4)
        editor.setTextCursor(cursor)
        window.sync.insert_timestamp()
        cursor.setPosition(0)
        cursor.insertText("xyz ")
        assert [a.start for a in window.sync.entries()] == [8]
        # Tekst wpisany w miejscu znacznika zaczyna się od znacznika.
        cursor.setPosition(8)
        cursor.insertText("nowe ")
        assert [a.start for a in window.sync.entries()] == [8]
        item = window.sync.manual_near(8)
        assert item is not None
        window.sync.remove(item)
        assert window.sync.entries() == []
