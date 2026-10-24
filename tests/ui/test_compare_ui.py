"""Porównanie dwóch wersji projektu w oknie (faza 14: ACC-62, ACC-63)."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.document.diff import FORMAT, REPLACE, SPEAKER
from transkryptor.document.project import ProjectState, save_project
from transkryptor.document.speakers import DEFAULT_SPEAKERS, INFORMANT, Speaker
from transkryptor.ui.compare_panel import ACCEPTED, PENDING, REJECTED
from transkryptor.ui.main_window import MainWindow

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")

TEXT_A = "tak było\npamientam dobrze"
# „było” → „buło”, „m” w „pamientam” w indeksie górnym, mówca drugiego
# akapitu B zamiast I.
TEXT_B = "tak buło\npamientam dobrze"
SUPERSCRIPT_B = ((11, 12),)
ANCHORS = (
    Anchor(0, 8, 0, 2000, SEGMENT),
    Anchor(9, 25, 2000, 5000, SEGMENT),
)


def state(text: str, ranges=(), assignments=None, **extra) -> ProjectState:
    return ProjectState(
        text=text,
        superscript_ranges=tuple(ranges),
        paragraph_speakers=(
            assignments if assignments is not None else {0: "B", 1: "I"}
        ),
        **extra,
    )


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.resize(1200, 760)
    win.show()
    win.session.apply_state(state(TEXT_A, anchors=ANCHORS), None, None, saved=True)
    return win


@pytest.fixture
def other(tmp_path) -> Path:
    path = tmp_path / "weryfikacja.transkr"
    save_project(state(TEXT_B, SUPERSCRIPT_B, {0: "B", 1: "B"}), path)
    return path


def editor_state(window: MainWindow) -> tuple[str, list[tuple[int, int]], dict]:
    document = window.document
    return (
        document.text,
        list(document.superscript_ranges),
        dict(document.paragraph_speakers),
    )


class TestCompare:
    def test_acc62_three_changes_selection_and_playback(
        self, qtbot, window, other, tmp_path, monkeypatch
    ) -> None:
        assert window.compare.compare_with(other)
        compare = window.compare
        assert [item.change.kind for item in compare.items] == [
            REPLACE,
            FORMAT,
            SPEAKER,
        ]
        assert window.compare.panel.list.count() == 3
        assert window.compare_card.isVisible()
        assert window.editor.isReadOnly()
        assert window.compare_view.plain_text() == TEXT_B

        compare.activate(0)
        assert window.editor.textCursor().selectedText() == "było"
        assert window.compare_view.textCursor().selectedText() == "buło"

        # Odsłuch: kotwica segmentu bieżącego dokumentu.
        if not SAMPLE_MP3.is_file():
            pytest.skip(f"brak nagrania testowego {SAMPLE_MP3}")
        audio = tmp_path / "nagranie.mp3"
        shutil.copy(SAMPLE_MP3, audio)
        window.player.load(audio)
        qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            window.player, "set_position", lambda ms: calls.append(("seek", ms))
        )
        monkeypatch.setattr(window.player, "play", lambda: calls.append(("play", 0)))
        compare.play(1)
        preroll = window.settings_store.current.player.segment_preroll_ms
        assert calls == [("seek", max(0, 2000 - preroll)), ("play", 0)]

    def test_acc63_accept_one_reject_rest_and_undo(self, window, other) -> None:
        compare = window.compare
        assert compare.compare_with(other)
        compare.accept(0)
        compare.reject(1)
        compare.reject(2)
        assert [item.state for item in compare.items] == [ACCEPTED, REJECTED, REJECTED]
        accepted: tuple[str, list, dict] = (
            "tak buło\npamientam dobrze",
            [],
            {0: "B", 1: "I"},
        )
        assert editor_state(window) == accepted

        compare.undo_action.trigger()
        assert [item.state for item in compare.items] == [ACCEPTED, REJECTED, PENDING]
        assert editor_state(window) == accepted

        # Cofnięcie przyjęcia przywraca tekst sprzed porównania.
        compare.undo_action.trigger()
        compare.undo_action.trigger()
        assert editor_state(window) == (TEXT_A, [], {0: "B", 1: "I"})
        assert [item.state for item in compare.items] == [PENDING] * 3
        compare.redo_action.trigger()
        assert editor_state(window) == accepted

    def test_accept_all_is_one_undo_step(self, window, other) -> None:
        compare = window.compare
        assert compare.compare_with(other)
        compare.accept_all()
        assert editor_state(window) == (TEXT_B, list(SUPERSCRIPT_B), {0: "B", 1: "B"})
        assert compare.stack.count() == 1
        compare.undo_action.trigger()
        assert editor_state(window) == (TEXT_A, [], {0: "B", 1: "I"})

    def test_ctrl_z_undoes_comparison_step(self, qtbot, window, other) -> None:
        compare = window.compare
        assert compare.compare_with(other)
        compare.reject(0)
        window.editor.setFocus()
        qtbot.keyClick(window.editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert compare.items[0].state == PENDING

    def test_finish_unlocks_editor_and_keeps_result(self, window, other) -> None:
        compare = window.compare
        assert compare.compare_with(other)
        compare.accept(0)
        compare.panel.finish_button.click()
        assert not compare.active
        assert not window.editor.isReadOnly()
        assert not window.compare_card.isVisible()
        assert window.document.text.startswith("tak buło")
        # Po zakończeniu skróty cofania należą znowu do edytora.
        assert not compare.undo_action.isEnabled()

    def test_identical_project_is_reported(
        self, window, tmp_path, no_blocking_dialogs
    ) -> None:
        path = tmp_path / "kopia.transkr"
        save_project(state(TEXT_A), path)
        assert not window.compare.compare_with(path)
        assert not window.compare.active
        assert no_blocking_dialogs[-1][0] == "information"

    def test_missing_speaker_is_added_on_accept(self, window, tmp_path) -> None:
        path = tmp_path / "mowcy.transkr"
        speakers = (*DEFAULT_SPEAKERS, Speaker("I2", "", INFORMANT))
        save_project(state(TEXT_A, (), {0: "B", 1: "I2"}, speakers=speakers), path)
        compare = window.compare
        assert compare.compare_with(path)
        (item,) = compare.items
        assert item.change.kind == SPEAKER
        compare.accept(0)
        assert window.document.speaker("I2") is not None
        assert window.document.paragraph_speakers == {0: "B", 1: "I2"}

    def test_opening_project_ends_comparison(self, window, other) -> None:
        assert window.compare.compare_with(other)
        window.session.apply_state(state("nowy tekst"), None, None, saved=True)
        assert not window.compare.active
        assert not window.editor.isReadOnly()
