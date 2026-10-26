"""Przejścia po niepewnych słowach i komentarzach oraz postęp weryfikacji."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox

from transkryptor.asr.engine import SegmentResult, TranscriptionResult, WordResult
from transkryptor.document.project import ProjectState
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.navigation import BACKWARD, FORWARD, step
from transkryptor.ui.shortcuts import (
    MARK_VERIFIED_ID,
    NEXT_COMMENT_ID,
    NEXT_UNCERTAIN_ID,
    NEXT_UNVERIFIED_ID,
    PREVIOUS_UNCERTAIN_ID,
    SHORTCUT_ACTIONS,
    effective_shortcuts,
    find_conflicts,
)

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


def words_result() -> TranscriptionResult:
    """Dwa segmenty; niepewne (pewność < 40%): „my”, „żeśmy”, „do”."""
    plan = [
        (0.0, 2.0, [("Wtedy", 0.95), ("my", 0.30), ("żeśmy", 0.12)]),
        (2.0, 4.0, [("poszli", 0.85), ("do", 0.39), ("lasu.", 0.41)]),
    ]
    segments = []
    for start, end, words in plan:
        length = (end - start) / len(words)
        results = tuple(
            WordResult(start + i * length, start + (i + 1) * length, f" {w}", p)
            for i, (w, p) in enumerate(words)
        )
        segments.append(
            SegmentResult(start, end, "".join(w.text for w in results), 0.7, results)
        )
    text = "".join(s.text for s in segments).strip()
    return TranscriptionResult(text=text, language="pl", segments=tuple(segments))


def place_cursor(window: MainWindow, position: int) -> None:
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(position)
    window.editor.setTextCursor(cursor)


def select(window: MainWindow, start: int, end: int) -> None:
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    window.editor.setTextCursor(cursor)


def selected(window: MainWindow) -> str:
    return window.editor.textCursor().selectedText()


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.resize(1100, 700)
    win.show()
    return win


@pytest.fixture
def audio(tmp_path) -> Path:
    target = tmp_path / "nagranie.mp3"
    shutil.copy(SAMPLE_MP3, target)
    return target


@pytest.fixture
def loaded(window, qtbot, audio) -> MainWindow:
    window._on_import_audio(str(audio))
    qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)
    return window


class TestStep:
    RANGES = [(0, 4), (10, 14), (20, 24)]

    def test_forward_from_cursor_and_selection(self) -> None:
        assert step(self.RANGES, (0, 0), FORWARD) == (0, False)
        assert step(self.RANGES, (0, 4), FORWARD) == (1, False)
        assert step(self.RANGES, (5, 5), FORWARD) == (1, False)
        assert step(self.RANGES, (20, 24), FORWARD) == (0, True)

    def test_backward(self) -> None:
        assert step(self.RANGES, (22, 22), BACKWARD) == (2, False)
        assert step(self.RANGES, (20, 24), BACKWARD) == (1, False)
        assert step(self.RANGES, (0, 4), BACKWARD) == (2, True)

    def test_empty(self) -> None:
        assert step([], (0, 0), FORWARD) is None


class TestShortcuts:
    def test_defaults_have_no_conflicts(self, qapp) -> None:
        defaults = effective_shortcuts({})
        assert find_conflicts(defaults) == []
        ids = {definition.id for definition in SHORTCUT_ACTIONS}
        assert {NEXT_UNCERTAIN_ID, NEXT_COMMENT_ID, MARK_VERIFIED_ID} <= ids
        assert defaults[NEXT_UNCERTAIN_ID] == ("F8",)
        assert defaults[MARK_VERIFIED_ID] == ("F9",)

    def test_actions_get_shortcuts(self, window) -> None:
        actions = window.shortcut_actions
        assert actions[NEXT_UNCERTAIN_ID].shortcut().toString() == "F8"
        assert actions[PREVIOUS_UNCERTAIN_ID].shortcut().toString() == "Shift+F8"
        assert actions[NEXT_COMMENT_ID].shortcut().toString() == "F7"
        assert actions[NEXT_UNVERIFIED_ID].shortcut().toString() == "Shift+F9"


class TestUncertainNavigation:
    def test_walks_uncertain_words_and_wraps(self, window) -> None:
        window._on_draft_ready(words_result())
        place_cursor(window, 0)
        sync = window.sync
        assert sync.go_to_uncertain(FORWARD)
        assert selected(window) == "my"
        assert (
            "Niepewne słowo 1 z 3 (pewność 30%)" in window.statusBar().currentMessage()
        )
        window.shortcut_actions[NEXT_UNCERTAIN_ID].trigger()
        assert selected(window) == "żeśmy"
        sync.go_to_uncertain(FORWARD)
        assert selected(window) == "do"
        sync.go_to_uncertain(FORWARD)
        assert selected(window) == "my"
        assert "od drugiego końca" in window.statusBar().currentMessage()
        window.shortcut_actions[PREVIOUS_UNCERTAIN_ID].trigger()
        assert selected(window) == "do"

    def test_corrected_word_is_skipped(self, window) -> None:
        window._on_draft_ready(words_result())
        text = window.editor.plain_text()
        select(window, text.index("żeśmy"), text.index("żeśmy") + 5)
        window.editor.textCursor().insertText("żeźmy")
        place_cursor(window, 0)
        window.sync.go_to_uncertain(FORWARD)
        window.sync.go_to_uncertain(FORWARD)
        assert selected(window) == "do"

    def test_without_uncertain_words(self, window) -> None:
        window.session.apply_state(ProjectState(text="sam tekst"), None, None, True)
        assert not window.sync.go_to_uncertain(FORWARD)
        assert window.statusBar().currentMessage() == (
            "W tekście nie ma niepewnych słów."
        )

    def test_plays_word_with_recording(self, loaded, monkeypatch) -> None:
        played = []
        monkeypatch.setattr(
            loaded.player,
            "play_loop_once",
            lambda start, end: played.append((start, end)),
        )
        loaded._on_draft_ready(words_result())
        place_cursor(loaded, 0)
        loaded.sync.go_to_uncertain(FORWARD)
        # „my”: 2/3 s - 4/3 s, z marginesem 150 ms.
        assert played == [(round(2000 / 3) - 150, round(4000 / 3) + 150)]


class TestCommentNavigation:
    @pytest.fixture
    def commented(self, window) -> MainWindow:
        text = "tak było pamientam dobrze a potem"
        window.session.apply_state(ProjectState(text=text), None, None, True)
        window.comments.ask = lambda *_args: ("Weryfikator", "Sprawdź")
        for word in ("dobrze", "było"):
            start = text.index(word)
            select(window, start, start + len(word))
            assert window.comments.add_from_selection()
        return window

    def test_walks_comments_in_text_order(self, commented) -> None:
        place_cursor(commented, 0)
        window = commented
        window.shortcut_actions[NEXT_COMMENT_ID].trigger()
        assert selected(window) == "było"
        assert window.comments.panel.selection() == (0, None)
        message = window.statusBar().currentMessage()
        assert message == "Komentarz 1 z 2 - Weryfikator: Sprawdź"
        window.comments.go_to(FORWARD)
        assert selected(window) == "dobrze"
        window.comments.go_to(FORWARD)
        assert selected(window) == "było"
        window.comments.go_to(BACKWARD)
        assert selected(window) == "dobrze"

    def test_without_comments(self, window) -> None:
        assert not window.comments.go_to(FORWARD)
        assert window.statusBar().currentMessage() == "Dokument nie ma komentarzy."


def seek(window: MainWindow, monkeypatch, position_ms: int) -> None:
    """Pozycja odtwarzacza bez czekania na dekoder."""
    monkeypatch.setattr(
        type(window.player), "position_ms", property(lambda _self: position_ms)
    )


class TestVerification:
    def test_hidden_without_recording(self, window) -> None:
        assert window.player_bar.verification_button.isHidden()
        assert not window.verification.mark_action.isEnabled()
        assert not window.verification.mark_until()

    def test_mark_until_position_and_progress(self, loaded, monkeypatch) -> None:
        window = loaded
        duration = window.player.duration_ms
        assert not window.player_bar.verification_button.isHidden()
        assert window.player_bar.verification_button.text() == "Sprawdzono 0%"
        seek(window, monkeypatch, duration // 2)
        window.shortcut_actions[MARK_VERIFIED_ID].trigger()
        assert window.verification.ranges == ((0, duration // 2),)
        assert window.player_bar.verification_button.text() == "Sprawdzono 50%"
        assert window.statusBar().currentMessage().startswith("Sprawdzono do 00:45")
        assert window.waveform.view.verified == [(0, duration // 2)]
        assert window.document.is_unsaved
        # Drugi raz w tym samym miejscu - nic nowego.
        assert not window.verification.mark_until()
        # Tuż przed końcem nagrania - całe nagranie.
        seek(window, monkeypatch, duration - 300)
        window.verification.mark_until()
        assert window.verification.ranges == ((0, duration),)
        assert window.player_bar.verification_button.text() == "Sprawdzono 100%"

    def test_go_to_unverified_moves_player_and_cursor(
        self, loaded, monkeypatch
    ) -> None:
        window = loaded
        window._on_draft_ready(words_result())
        seek(window, monkeypatch, 2500)
        window.verification.mark_until()
        seeks: list[int] = []
        monkeypatch.setattr(window.player, "set_position", seeks.append)
        place_cursor(window, 0)
        window.shortcut_actions[NEXT_UNVERIFIED_ID].trigger()
        assert seeks == [2500]
        # Kursor na początku segmentu trwającego w 2,5 s („poszli do lasu.”).
        text = window.editor.plain_text()
        assert window.editor.textCursor().position() == text.index("poszli")
        assert window.statusBar().currentMessage() == "Niesprawdzone miejsce: 00:02"

    def test_selection_marks_and_unmarks(self, loaded) -> None:
        window = loaded
        window._on_draft_ready(words_result())
        text = window.editor.plain_text()
        select(window, text.index("poszli"), len(text))
        assert window.verification.mark_selection(True)
        assert window.verification.ranges == ((2000, 4000),)
        # Słowo „do” (2,67-3,33 s) - tylko ono, nie cały segment.
        select(window, text.index("do"), text.index("do") + 2)
        assert window.verification.mark_selection(False)
        assert window.verification.ranges == ((2000, 2667), (3333, 4000))

    def test_selection_without_time(self, loaded) -> None:
        window = loaded
        window.editor.setPlainText("bez kotwic")
        select(window, 0, 3)
        assert not window.verification.mark_selection(True)
        assert window.statusBar().currentMessage() == (
            "Zaznaczony tekst nie jest powiązany z czasem nagrania."
        )

    def test_context_menu_offers_marking(self, loaded) -> None:
        from PySide6.QtWidgets import QMenu

        window = loaded
        window._on_draft_ready(words_result())
        start = window.editor.plain_text().index("Wtedy")
        select(window, start, start + 5)
        menu = QMenu()
        window.verification.extend_context_menu(menu, 0)
        texts = [action.text() for action in menu.actions() if action.text()]
        assert texts == ["Oznacz zaznaczony fragment jako sprawdzony"]
        window.verification.mark_selection(True)
        menu = QMenu()
        window.verification.extend_context_menu(menu, 0)
        assert "Oznacz zaznaczony fragment jako niesprawdzony" in [
            action.text() for action in menu.actions()
        ]

    def test_ranges_survive_project_and_clear_with_new_recording(
        self, loaded, add_window, qtbot, tmp_path, monkeypatch
    ) -> None:
        window = loaded
        seek(window, monkeypatch, 30_000)
        window.verification.mark_until()
        path = tmp_path / "projekt.transkr"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(path), "")),
        )
        assert window.session.save_project_as()
        monkeypatch.undo()

        other = add_window(MainWindow())
        assert other.session.open_project(path)
        assert other.verification.ranges == ((0, 30_000),)
        qtbot.waitUntil(lambda: other.player_bar.has_media, timeout=10000)
        assert other.player_bar.verification_button.text() == "Sprawdzono 33%"

        # Zmiana nagrania pyta o postęp i go usuwa.
        questions: list[str] = []

        def yes(_parent, _title, text, *_args):
            questions.append(text)
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", staticmethod(yes))
        second = tmp_path / "drugie.mp3"
        shutil.copy(SAMPLE_MP3, second)
        other._on_import_audio(str(second))
        assert "Postęp weryfikacji nagrania" in questions[0]
        assert other.verification.ranges == ()

    def test_clear_asks_first(self, loaded, monkeypatch) -> None:
        window = loaded
        seek(window, monkeypatch, 10_000)
        window.verification.mark_until()
        assert not window.verification.clear_with_confirmation()  # „Nie”
        assert window.verification.ranges
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.Yes),
        )
        assert window.verification.clear_with_confirmation()
        assert window.verification.ranges == ()
        assert not window.verification.clear_action.isEnabled()

    def test_locked_during_transcription(self, loaded) -> None:
        window = loaded
        window._set_ui_locked(True)
        assert not window.verification.mark_action.isEnabled()
        assert not window.shortcut_actions[NEXT_UNCERTAIN_ID].isEnabled()
        window._set_ui_locked(False)
        assert window.verification.mark_action.isEnabled()
        assert window.shortcut_actions[NEXT_UNCERTAIN_ID].isEnabled()
