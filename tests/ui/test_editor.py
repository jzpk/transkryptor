"""Testy edytora: indeks górny, wstawianie markerów, synchronizacja."""

from PySide6.QtGui import QTextCharFormat, QTextCursor

from transkryptor.document.model import Document
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.markers import (
    ASIDE_TEXT,
    DOUBT_TEXT,
    ODDITY_TEXT,
    OMITTED_TEXT,
    PAUSE_TEXT,
)


def select(editor: TranscriptionEditor, start: int, end: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)


def is_superscript_at(editor: TranscriptionEditor, start: int, end: int) -> bool:
    select(editor, start, end)
    return (
        editor.textCursor().charFormat().verticalAlignment()
        == QTextCharFormat.VerticalAlignment.AlignSuperScript
    )


class TestSuperscript:
    """ACC-02: zaznaczenie m/n/u i indeks górny."""

    def test_selection_gets_superscript_and_rest_is_unchanged(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("pamientam")
        select(editor, 3, 4)  # "m"
        editor.toggle_superscript()
        assert is_superscript_at(editor, 3, 4)
        assert not is_superscript_at(editor, 0, 3)
        assert not is_superscript_at(editor, 4, 9)
        assert editor.toPlainText() == "pamientam"

    def test_toggle_removes_superscript(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("bendzie")
        select(editor, 0, 2)
        editor.toggle_superscript()
        assert is_superscript_at(editor, 0, 2)
        editor.toggle_superscript()
        assert not is_superscript_at(editor, 0, 2)

    def test_without_selection_nothing_changes(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("kuosa")
        editor.toggle_superscript()
        doc = Document()
        editor.sync_to_document(doc)
        assert doc.superscript_ranges == []


class TestMarkers:
    """ACC-03 i REQ-05: wstawianie markerów notacji."""

    def test_pause_inserts_exactly_space_dots_space(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("rzeczy")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        editor.insert_marker(PAUSE_TEXT)
        assert editor.toPlainText() == "rzeczy ... "

    def test_all_markers_insert_their_text(self, qtbot) -> None:
        for marker in (ODDITY_TEXT, DOUBT_TEXT, OMITTED_TEXT):
            editor = TranscriptionEditor()
            qtbot.addWidget(editor)
            editor.insert_marker(marker)
            assert editor.toPlainText() == marker

    def test_aside_places_cursor_between_brackets(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.insert_marker(ASIDE_TEXT)
        assert editor.toPlainText() == "[...]"
        assert editor.textCursor().position() == 3


class TestSync:
    """Synchronizacja edytora z modelem dokumentu z fazy 01."""

    def test_text_and_ranges_are_synced(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("pamientam uóna")
        select(editor, 3, 4)
        editor.toggle_superscript()
        doc = Document()
        editor.sync_to_document(doc)
        assert doc.text == "pamientam uóna"
        assert doc.superscript_ranges == [(3, 4)]
        assert doc.revision == 1

    def test_sync_after_plain_edit_clears_ranges(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("pamientam")
        select(editor, 3, 4)
        editor.toggle_superscript()
        editor.selectAll()
        editor.textCursor().insertText("nowy tekst")
        doc = Document()
        editor.sync_to_document(doc)
        assert doc.text == "nowy tekst"
        assert doc.superscript_ranges == []


class TestUndoRedo:
    """NFR-04: standardowe cofanie i ponawianie."""

    def test_undo_redo_marker_insert(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("tekst")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        editor.insert_marker(PAUSE_TEXT)
        assert editor.toPlainText() == "tekst ... "
        editor.undo()
        assert editor.toPlainText() == "tekst"
        editor.redo()
        assert editor.toPlainText() == "tekst ... "

    def test_undo_superscript_formatting(self, qtbot) -> None:
        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        editor.setPlainText("pamientam")
        select(editor, 3, 4)
        editor.toggle_superscript()
        editor.undo()
        assert not is_superscript_at(editor, 3, 4)
