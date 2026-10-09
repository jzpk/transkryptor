"""Testy paska wyszukiwania i zamiany (propozycja 20, ACC-26, ACC-27)."""

import time

import pytest
from docx import Document as DocxDocument
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from transkryptor.export.docx_export import export_docx
from transkryptor.ui.main_window import MainWindow


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def show(qtbot, window: MainWindow) -> None:
    """Skróty klawiaturowe działają tylko w pokazanym, aktywnym oknie."""
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is window, timeout=3000)


def search_for(window: MainWindow, query: str, *, replace: str | None = None) -> None:
    if replace is None:
        window.search_actions["find"].trigger()
    else:
        window.search_actions["replace"].trigger()
        window.search_bar.replace_edit.setText(replace)
    window.search_bar.find_edit.setText(query)
    window.search.refresh()


def superscript_text(window: MainWindow) -> list[str]:
    window.run_validation_now()
    text = window.document.text
    return [text[s:e] for s, e in window.document.superscript_ranges]


class TestFind:
    def test_ctrl_f_from_editor_opens_bar_without_typing(self, qtbot, window) -> None:
        show(qtbot, window)
        window.editor.setPlainText("tak")
        window.editor.setFocus()
        qtbot.keyClick(window.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert not window.search_bar.isHidden()
        assert not window.search_bar.is_replace_mode()
        assert window.editor.toPlainText() == "tak"

    def test_selection_prefills_query(self, window) -> None:
        window.editor.setPlainText("som i som")
        window.editor.setTextCursor(window.editor.track_range(0, 3))
        window.search_actions["find"].trigger()
        assert window.search_bar.find_edit.text() == "som"

    def test_count_and_highlights(self, window) -> None:
        window.editor.setPlainText("som i Som i sóm")
        search_for(window, "som")
        assert window.search.matches == [(0, 3), (6, 9)]
        assert window.search_bar.count_label.text() == "2 wyn."
        assert len(window.editor.extraSelections()) == 2

    def test_next_previous_wrap_and_select(self, window) -> None:
        window.editor.setPlainText("som i som")
        search_for(window, "som")
        cursor = window.editor.textCursor()
        cursor.setPosition(0)
        window.editor.setTextCursor(cursor)
        window.search_actions["find_next"].trigger()
        assert window.editor.textCursor().selectedText() == "som"
        assert window.search_bar.count_label.text() == "1 z 2"
        window.search_actions["find_next"].trigger()
        assert window.search_bar.count_label.text() == "2 z 2"
        window.search_actions["find_next"].trigger()
        assert window.search_bar.count_label.text() == "1 z 2"
        window.search_actions["find_previous"].trigger()
        assert window.search_bar.count_label.text() == "2 z 2"

    def test_highlights_follow_edits(self, qtbot, window) -> None:
        window.editor.setPlainText("som")
        search_for(window, "som")
        window.editor.setPlainText("som som som")
        qtbot.waitUntil(lambda: len(window.search.matches) == 3, timeout=1000)

    def test_escape_closes_and_returns_focus(self, qtbot, window) -> None:
        show(qtbot, window)
        window.editor.setPlainText("som")
        search_for(window, "som")
        window.search_bar.find_edit.setFocus()
        qtbot.keyClick(window.search_bar.find_edit, Qt.Key.Key_Escape)
        assert window.search_bar.isHidden()
        assert window.editor.extraSelections() == []

    def test_whole_words_and_case(self, window) -> None:
        window.editor.setPlainText("Tak taki tak")
        search_for(window, "tak")
        window.search_bar.whole_words_check.setChecked(True)
        assert window.search.matches == [(0, 3), (9, 12)]
        window.search_bar.case_check.setChecked(True)
        assert window.search.matches == [(9, 12)]


class TestReplace:
    def test_acc26_replace_all_with_superscript(self, window, tmp_path) -> None:
        window.editor.setPlainText("będzie tak, będziesz i będzie")
        search_for(window, "będzie", replace="be^ndzie")
        window.search_bar.whole_words_check.setChecked(True)
        assert "<sup>n</sup>" in window.search_bar.preview_label.text()
        assert window.search.replace_all() == 2
        assert window.editor.toPlainText() == "bendzie tak, będziesz i bendzie"
        assert superscript_text(window) == ["n", "n"]
        # Podświetlenie wyszukiwania nie trafia do DOCX.
        path = tmp_path / "wynik.docx"
        export_docx(window.document, path)
        runs = DocxDocument(str(path)).paragraphs[-1].runs
        assert all(not run.font.highlight_color for run in runs)
        assert [r.text for r in runs if r.font.superscript] == ["n", "n"]
        # Jedno cofnięcie przywraca stan sprzed zamiany.
        window.editor.undo()
        assert window.editor.toPlainText() == "będzie tak, będziesz i będzie"
        assert superscript_text(window) == []

    def test_replacement_does_not_inherit_superscript(self, window) -> None:
        window.editor.setPlainText("som tak")
        window.editor.setTextCursor(window.editor.track_range(2, 3))
        window.editor.toggle_superscript()
        search_for(window, "tak", replace="nie")
        window.search.replace_all()
        assert superscript_text(window) == ["m"]

    def test_replace_current_moves_to_next(self, window) -> None:
        window.editor.setPlainText("som som")
        search_for(window, "som", replace="sóm")
        window.search_bar.replace_button.click()  # pierwsze: zaznacza trafienie
        window.search_bar.replace_button.click()
        assert window.editor.toPlainText() == "sóm som"
        assert window.editor.textCursor().selectedText() == "som"
        window.search_bar.replace_button.click()
        assert window.editor.toPlainText() == "sóm sóm"

    def test_replace_with_trailing_caret_shows_error(self, window) -> None:
        window.editor.setPlainText("som")
        search_for(window, "som", replace="so^")
        assert window.search_bar.error_label.isVisibleTo(window.search_bar)
        assert window.search.replace_all() == 0
        assert window.editor.toPlainText() == "som"


class TestErrorsAndLock:
    def test_acc27_invalid_regex(self, window) -> None:
        window.editor.setPlainText("som (tak")
        window.search_actions["replace"].trigger()
        window.search_bar.regex_check.setChecked(True)
        window.search_bar.replace_edit.setText("x")
        window.search_bar.find_edit.setText("(tak")
        assert window.search_bar.error_label.isVisibleTo(window.search_bar)
        assert "wyrażenie" in window.search_bar.error_label.text()
        assert window.search.replace_all() == 0
        assert window.editor.toPlainText() == "som (tak"
        window.search_bar.find_edit.setText("\\(tak")
        assert not window.search_bar.error_label.isVisibleTo(window.search_bar)
        assert window.search.matches == [(4, 8)]

    def test_search_locked_during_asr(self, window) -> None:
        window._set_ui_locked(True)
        assert not any(a.isEnabled() for a in window.search_actions.values())
        window._set_ui_locked(False)
        assert all(a.isEnabled() for a in window.search_actions.values())


class TestManyMatchesAndPositions:
    def test_only_visible_matches_are_highlighted(self, qtbot, window) -> None:
        """PERF-06: 10 tys. trafień — pełny licznik, podświetlenia na ekranie."""
        show(qtbot, window)
        window.editor.setPlainText("\n".join(["e"] * 10_000))
        search_for(window, "e")
        assert len(window.search.matches) == 10_000
        assert "10000" in window.search_bar.count_label.text()
        highlighted = window.editor.extraSelections()
        assert 0 < len(highlighted) < 200
        first_visible = min(s.cursor.selectionStart() for s in highlighted)
        window.editor.verticalScrollBar().setValue(
            window.editor.verticalScrollBar().maximum()
        )
        scrolled = window.editor.extraSelections()
        assert 0 < len(scrolled) < 200
        assert min(s.cursor.selectionStart() for s in scrolled) > first_visible

    def test_editing_with_many_matches_stays_fast(self, qtbot, window) -> None:
        show(qtbot, window)
        window.editor.setPlainText("e " * 10_000)
        search_for(window, "e")
        cursor = window.editor.textCursor()
        cursor.setPosition(0)
        window.editor.setTextCursor(cursor)
        started = time.perf_counter()
        for _ in range(5):
            window.editor.insertPlainText("x")
            window.search.refresh()
        assert (time.perf_counter() - started) / 5 < 0.25
        assert len(window.search.matches) == 10_000

    def test_find_next_after_emoji_selects_right_match(self, window) -> None:
        """BUG-02: pozycja kursora za emoji przeliczana na punkty kodowe."""
        window.editor.setPlainText("😀 som 😀 som")
        search_for(window, "som")
        assert window.search.matches == [(2, 5), (8, 11)]
        window.editor.setTextCursor(window.editor.track_range(2, 5))
        window.search_actions["find_next"].trigger()
        assert window.search.current_index == 1
        assert window.editor.selection_range(window.editor.textCursor()) == (8, 11)
        window.search_actions["find_previous"].trigger()
        assert window.search.current_index == 0

    def test_expensive_regex_shows_message(self, window) -> None:
        window.editor.setPlainText("a" * 60 + "b")
        window.search_actions["find"].trigger()
        window.search_bar.regex_check.setChecked(True)
        started = time.monotonic()
        window.search_bar.find_edit.setText("(a|aa)+$")
        assert time.monotonic() - started < 1.5
        assert window.search.matches == []
        assert "zbyt kosztowny" in window.search_bar.error_label.text()
