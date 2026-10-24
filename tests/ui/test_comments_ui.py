"""Komentarze recenzji w oknie (faza 14: ACC-64)."""

from pathlib import Path

import pytest
from docx import Document as DocxReader
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog, QMessageBox

from transkryptor.document.project import ProjectState, load_project
from transkryptor.ui.highlights import COMMENT_LAYER
from transkryptor.ui.main_window import MainWindow

TEXT = "tak było pamientam dobrze"


def select(window: MainWindow, start: int, end: int) -> None:
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    window.editor.setTextCursor(cursor)


def answer(window: MainWindow, author: str, text: str) -> list[tuple[str, str]]:
    """Atrapa okna komentarza: zwraca podanego autora i treść."""
    calls: list[tuple[str, str]] = []

    def fake(_parent, title, default_author, _text="", _context=""):
        calls.append((title, default_author))
        return author, text

    window.comments.ask = fake
    return calls


def save_as(window: MainWindow, path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )
    assert window.session.save_project_as()


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.resize(1100, 700)
    win.show()
    win.session.apply_state(ProjectState(text=TEXT), None, None, saved=True)
    return win


def test_acc64_comment_thread_survives_save_and_edits(
    window, add_window, tmp_path, monkeypatch
) -> None:
    # Weryfikator komentuje „było” i zapisuje projekt.
    answer(window, "Weryfikator", "Raczej „buło”?")
    select(window, 4, 8)
    assert window.comments.add_from_selection()
    assert window.document.is_unsaved
    path = tmp_path / "projekt.transkr"
    save_as(window, path, monkeypatch)

    # Transkrybent otwiera projekt i odpowiada.
    other = add_window(MainWindow())
    assert other.session.open_project(path)
    (comment,) = other.comments.entries()
    assert (comment.author, comment.text, comment.quote) == (
        "Weryfikator",
        "Raczej „buło”?",
        "było",
    )
    answer(other, "Transkrybent", "Poprawione.")
    assert other.comments.reply(0)

    # Edycja wokół fragmentu: komentarz zostaje przy nim.
    cursor = QTextCursor(other.editor.document())
    cursor.setPosition(0)
    cursor.insertText("No ")
    cursor.setPosition(len("No tak było"))
    cursor.insertText(" sobie")
    (comment,) = other.comments.entries()
    text = other.editor.plain_text()
    assert text[comment.start : comment.end] == "było"
    assert other.session.save_project()

    (saved,) = load_project(path).comments
    assert saved.quote == "było"
    assert (saved.start, saved.end) == (7, 11)
    assert [(r.author, r.text) for r in saved.replies] == [
        ("Transkrybent", "Poprawione.")
    ]


def test_comment_needs_selection(window, no_blocking_dialogs) -> None:
    answer(window, "A", "uwaga")
    assert not window.comments.add_from_selection()
    assert no_blocking_dialogs[-1][0] == "information"
    assert window.comments.items == []


def test_author_is_remembered(window) -> None:
    calls = answer(window, "Ewa K.", "uwaga")
    select(window, 0, 3)
    window.comments.add_from_selection()
    assert window.settings_store.current.review.comment_author == "Ewa K."
    select(window, 4, 8)
    window.comments.add_from_selection()
    assert calls[-1][1] == "Ewa K."


def test_deleted_fragment_keeps_comment(window) -> None:
    answer(window, "A", "uwaga")
    select(window, 4, 8)
    window.comments.add_from_selection()
    select(window, 3, 8)
    window.editor.textCursor().removeSelectedText()
    (comment,) = window.comments.entries()
    assert comment.is_point
    assert comment.quote == "było"


def test_highlight_and_tooltip(window) -> None:
    answer(window, "A", "uwaga")
    select(window, 4, 8)
    window.comments.add_from_selection()
    assert len(window.editor.highlight_layer(COMMENT_LAYER)) == 1
    tip = window.comments.tooltip_at(5)
    assert tip is not None and "uwaga" in tip
    assert window.comments.tooltip_at(0) is None


def test_edit_and_remove(window, monkeypatch) -> None:
    answer(window, "A", "uwaga")
    select(window, 4, 8)
    window.comments.add_from_selection()
    answer(window, "A", "odpowiedź")
    window.comments.reply(0)
    answer(window, "A", "nowa treść")
    assert window.comments.edit(0)
    assert window.comments.entries()[0].text == "nowa treść"
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    assert window.comments.remove(0, 0)
    assert window.comments.entries()[0].replies == ()
    assert window.comments.remove(0)
    assert window.comments.entries() == []


def test_new_document_clears_comments(window) -> None:
    answer(window, "A", "uwaga")
    select(window, 4, 8)
    window.comments.add_from_selection()
    window.document.mark_saved()
    window.document.mark_exported()
    window.session.new_document()
    assert window.comments.items == []


def test_docx_export_contains_comments(window, tmp_path, monkeypatch) -> None:
    answer(window, "Weryfikator", "uwaga")
    select(window, 4, 8)
    window.comments.add_from_selection()
    target = tmp_path / "eksport.docx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    window.exporter.export()
    (comment,) = list(DocxReader(str(target)).comments)
    assert comment.author == "Weryfikator"
    window.exporter.export(anonymize=True)
    assert list(DocxReader(str(target)).comments) == []
