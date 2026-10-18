"""Testy UI eksportu do wielu formatów (faza 12, ACC-54)."""

from pathlib import Path

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QFileDialog

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.export.options import UNTIMED_SKIP, ExportOptions
from transkryptor.export.registry import exporter_by_key
from transkryptor.ui.export_dialog import ExportDialog
from transkryptor.ui.main_window import MainWindow

TEXT = "Rok urodzenia?\nTysionc dziewińćset\nA brat?"


def save_dialog(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )


def make_window(add_window, anchors=True) -> MainWindow:
    window = add_window(MainWindow())
    window.editor.load_content(TEXT, [], {0: "B", 1: "I"})
    window.session.mark_editor_changed()
    if anchors:
        window.sync.restore(
            [Anchor(0, 14, 0, 1500, SEGMENT), Anchor(15, 34, 1600, 4000, SEGMENT)]
        )
    return window


def test_timed_formats_need_anchors(add_window) -> None:
    window = make_window(add_window, anchors=False)
    dialog = window.exporter.create_dialog()
    model = dialog.format_combo.model()
    assert isinstance(model, QStandardItemModel)
    enabled = {
        dialog.format_combo.itemData(row): model.item(row).isEnabled()
        for row in range(model.rowCount())
    }
    assert enabled["docx"] and enabled["txt"] and not enabled["eaf"]
    assert not dialog.times_hint.isHidden()
    assert make_window(add_window).exporter.has_times()


def test_dialog_shows_only_relevant_options(qtbot) -> None:
    dialog = ExportDialog("srt", has_times=True)
    qtbot.addWidget(dialog)
    form = dialog._form
    assert dialog.exporter.key == "srt"
    assert form.isRowVisible(dialog.untimed_combo)
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("pdf"))
    assert not form.isRowVisible(dialog.superscript_combo)
    assert not form.isRowVisible(dialog.untimed_combo)
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("txt"))
    assert form.isRowVisible(dialog.superscript_combo)


def test_srt_export_reports_skipped_fragments(
    add_window, monkeypatch, tmp_path, no_blocking_dialogs
) -> None:
    """ACC-54: raport wskazuje fragmenty pominięte zgodnie z opcją."""
    window = make_window(add_window)
    target = tmp_path / "napisy.srt"
    save_dialog(monkeypatch, tmp_path / "napisy")

    assert window.exporter.export_with(
        exporter_by_key("srt"), ExportOptions(untimed=UNTIMED_SKIP), False
    )

    content = target.read_text(encoding="utf-8")
    assert "B: Rok urodzenia?" in content and "A brat?" not in content
    report = window.exporter.last_report
    assert report is not None and "A brat?" in report.warnings[0]
    warnings = [call for call in no_blocking_dialogs if call[0] == "warning"]
    assert warnings and "A brat?" in warnings[-1][2]
    # Wybór okna jest pamiętany, a eksport inny niż DOCX nie zdejmuje ostrzeżenia.
    assert window.settings_store.current.export.last_format == "srt"
    assert window.settings_store.current.export.untimed_mode == UNTIMED_SKIP
    assert window.document.is_dirty


def test_textgrid_suffix_is_added(add_window, monkeypatch, tmp_path) -> None:
    window = make_window(add_window)
    save_dialog(monkeypatch, tmp_path / "praat")
    assert window.exporter.export_with(
        exporter_by_key("textgrid"), ExportOptions(), False
    )
    assert (
        (tmp_path / "praat.TextGrid")
        .read_text(encoding="utf-8")
        .startswith('File type = "ooTextFile"')
    )


def test_export_as_action_opens_dialog(add_window, monkeypatch) -> None:
    window = make_window(add_window)
    opened: list[str] = []

    def fake_exec(dialog: ExportDialog) -> int:
        opened.append(dialog.exporter.key)
        return 0

    monkeypatch.setattr(ExportDialog, "exec", fake_exec)
    window.export_as_action.trigger()
    assert opened == ["docx"]


def test_docx_export_still_marks_exported(add_window, monkeypatch, tmp_path) -> None:
    window = make_window(add_window)
    save_dialog(monkeypatch, tmp_path / "wywiad.docx")
    window.export_action.trigger()
    assert (tmp_path / "wywiad.docx").is_file()
    assert not window.document.is_dirty
