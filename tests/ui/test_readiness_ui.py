"""Raport „Gotowość do oddania” w oknie i przed eksportem."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog

from transkryptor.document.project import ProjectState
from transkryptor.document.readiness import (
    CATEGORIES,
    COMMENTS,
    METADATA,
    SPEAKERS,
    WARNINGS,
)
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.readiness_dialog import GO_TO, ReadinessDialog

TEXT = "tak było  pamientam"


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.show()
    win.session.apply_state(ProjectState(text=TEXT), None, None, saved=True)
    return win


def fill_metadata(window: MainWindow) -> None:
    for key in window.metadata_form.edits:
        window.metadata_form.set_value(key, "x")


def comment(window: MainWindow, start: int, end: int) -> None:
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    window.editor.setTextCursor(cursor)
    window.comments.ask = lambda *_args: ("A", "sprawdź")
    assert window.comments.add_from_selection()


def export_target(monkeypatch, tmp_path):
    target = tmp_path / "eksport.docx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    return target


def test_report_collects_problems_from_panels(window) -> None:
    comment(window, 0, 3)
    report = window._readiness_report()
    assert report.of(WARNINGS)  # podwójna spacja
    assert [i.label for i in report.of(COMMENTS)] == ["sprawdź"]
    assert report.of(SPEAKERS) == []
    assert report.of(METADATA)

    window.comments.toggle_resolved(0)
    fill_metadata(window)
    report = window._readiness_report()
    assert report.of(COMMENTS) == [] and report.of(METADATA) == []


def test_export_shows_report_and_can_be_cancelled(
    window, monkeypatch, tmp_path, no_blocking_dialogs
) -> None:
    target = export_target(monkeypatch, tmp_path)
    window.readiness.run = lambda dialog: int(ReadinessDialog.DialogCode.Rejected)
    window.exporter.export()
    assert not target.exists()

    window.readiness.run = lambda dialog: int(ReadinessDialog.DialogCode.Accepted)
    window.exporter.export()
    assert target.exists()


def test_ready_document_exports_without_report(
    qtbot, add_window, monkeypatch, tmp_path
) -> None:
    window = add_window(MainWindow())
    window.session.apply_state(ProjectState(text="tak było"), None, None, saved=True)
    fill_metadata(window)
    shown: list[ReadinessDialog] = []
    window.readiness.run = record(shown)
    target = export_target(monkeypatch, tmp_path)
    window.exporter.export()
    assert target.exists() and shown == []


def test_check_before_export_can_be_turned_off(window, monkeypatch, tmp_path) -> None:
    def untick(dialog: ReadinessDialog) -> int:
        dialog.check_box.setChecked(False)
        return int(ReadinessDialog.DialogCode.Rejected)

    window.readiness.run = untick
    export_target(monkeypatch, tmp_path)
    window.exporter.export()
    assert window.settings_store.current.export.readiness_check is False

    shown: list[ReadinessDialog] = []
    window.readiness.run = record(shown)
    window.exporter.export()
    assert shown == []
    # Z menu raport otwiera się zawsze.
    window.readiness_action.trigger()
    assert len(shown) == 1


def test_choosing_an_item_goes_to_text_or_field(window) -> None:
    comment(window, 4, 8)

    def choose(category: str):
        def run(dialog: ReadinessDialog) -> int:
            issue, *_rest = dialog_issues(dialog, category)
            dialog.choose(issue)
            return GO_TO

        return run

    window.readiness.run = choose(COMMENTS)
    window.readiness.show()
    assert window.editor.textCursor().selectedText() == "było"

    window.readiness.run = choose(METADATA)
    window.readiness.show()
    assert window.metadata_form.details.isVisibleTo(window)
    focused = window.focusWidget()
    assert focused in window.metadata_form.edits.values()


def record(shown: list[ReadinessDialog]):
    def run(dialog: ReadinessDialog) -> int:
        shown.append(dialog)
        return 0

    return run


def dialog_issues(dialog: ReadinessDialog, category: str) -> list:
    top = dialog.tree.topLevelItem(CATEGORIES.index(category))
    assert top is not None
    issues = []
    for index in range(top.childCount()):
        child = top.child(index)
        assert child is not None
        issues.append(child.data(0, Qt.ItemDataRole.UserRole))
    return issues
