"""Seria nagrań w oknie: import ZIP, „Następne nagranie” i folder w korpusie."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from transkryptor.document.project import load_project
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.shortcuts import SERIES_NEXT_ID

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


def _series_zip(tmp_path: Path, count: int = 3) -> Path:
    archive = tmp_path / "wywiady.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for number in range(1, count + 1):
            handle.write(SAMPLE_MP3, f"wywiady/w{number}.mp3")
    return archive


def _window(qtbot, add_window, archive: Path, target: Path) -> MainWindow:
    window = add_window(MainWindow())
    window.series.choose_archive = lambda: archive
    window.series.choose_directory = lambda _title, _start: target
    return window


def _import(window: MainWindow) -> bool:
    """Import serii z czekaniem na koniec rozpakowania w tle."""
    started = window.series.import_dialog()
    window.series.importer.wait()
    return started


def _current(window: MainWindow) -> str | None:
    path = window.player.source_path
    return path.name if path is not None else None


def test_import_opens_first_recording(qtbot, add_window, tmp_path) -> None:
    window = _window(qtbot, add_window, _series_zip(tmp_path), tmp_path / "out")
    assert _import(window)
    folder = tmp_path / "out" / "wywiady"
    assert sorted(p.name for p in folder.iterdir()) == ["w1.mp3", "w2.mp3", "w3.mp3"]
    assert _current(window) == "w1.mp3"
    assert window.series.next_action.isEnabled()
    assert not window.series.button.isHidden()
    assert "1" in window.series.button.text() and "3" in window.series.button.text()


def test_next_saves_project_and_opens_next(qtbot, add_window, tmp_path) -> None:
    window = _window(qtbot, add_window, _series_zip(tmp_path), tmp_path / "out")
    _import(window)
    folder = tmp_path / "out" / "wywiady"
    window.editor.setPlainText("pierwszy wywiad")
    assert window.series.open_next()
    assert load_project(folder / "w1.transkr").text == "pierwszy wywiad"
    assert _current(window) == "w2.mp3"
    assert window.session.project_path is None
    assert window.editor.plain_text() == ""
    # Nietknięte nagranie nie dostaje projektu.
    assert window.series.open_next()
    assert not (folder / "w2.transkr").exists()
    assert _current(window) == "w3.mp3"
    assert not window.series.next_action.isEnabled()
    assert not window.series.open_next()


def test_next_reopens_existing_project(qtbot, add_window, tmp_path) -> None:
    window = _window(qtbot, add_window, _series_zip(tmp_path, 2), tmp_path / "out")
    _import(window)
    folder = tmp_path / "out" / "wywiady"
    window.editor.setPlainText("jeden")
    window.series.open_next()
    window.editor.setPlainText("dwa")
    window.session.write_project(folder / "w2.transkr")
    # Folder nagrań wznawia pracę od pierwszego nagrania bez projektu - tu
    # wszystkie mają projekt, więc od pierwszego.
    window.series.choose_directory = lambda _title, _start: folder
    assert window.series.folder_dialog()
    assert window.session.project_path == folder / "w1.transkr"
    assert window.editor.plain_text() == "jeden"
    assert window.series.open_next()
    assert window.session.project_path == folder / "w2.transkr"
    assert window.editor.plain_text() == "dwa"


def test_folder_resumes_at_first_unfinished(qtbot, add_window, tmp_path) -> None:
    folder = tmp_path / "seria"
    folder.mkdir()
    for name in ("a1.mp3", "a2.mp3"):
        shutil.copy(SAMPLE_MP3, folder / name)
    (folder / "a1.transkr").write_text("{}", encoding="utf-8")
    window = _window(qtbot, add_window, tmp_path / "none.zip", folder)
    assert window.series.folder_dialog()
    assert _current(window) == "a2.mp3"


def test_empty_folder_is_reported(
    qtbot, add_window, tmp_path, no_blocking_dialogs
) -> None:
    window = _window(qtbot, add_window, tmp_path / "none.zip", tmp_path)
    assert not window.series.folder_dialog()
    assert no_blocking_dialogs[-1][0] == "information"


def test_show_in_corpus_uses_series_folder(qtbot, add_window, tmp_path) -> None:
    window = _window(qtbot, add_window, _series_zip(tmp_path, 2), tmp_path / "out")
    _import(window)
    window.series.show_in_corpus()
    dialog = window.corpus.dialog
    assert dialog is not None
    dialog.wait()
    assert dialog.folder == tmp_path / "out" / "wywiady"
    dialog.close()


def test_series_commands_are_registered_and_lockable(qtbot, add_window) -> None:
    window = add_window(MainWindow())
    assert window.shortcut_actions[SERIES_NEXT_ID] is window.series.next_action
    assert window.series.import_action in window.main_toolbar.open_menu.menu.actions()
    assert window.series.button.isHidden()
    window.series.set_locked(True)
    assert not window.series.import_action.isEnabled()
    window.series.set_locked(False)
    assert window.series.import_action.isEnabled()


def test_overview_lists_series_and_opens_recording(qtbot, add_window, tmp_path) -> None:
    folder = tmp_path / "seria"
    folder.mkdir()
    for name in ("a1.mp3", "a2.mp3", "a3.mp3"):
        shutil.copy(SAMPLE_MP3, folder / name)
    window = _window(qtbot, add_window, tmp_path / "none.zip", folder)
    window.series.folder_dialog()
    window.editor.setPlainText("pierwszy")
    window.session.write_project(folder / "a1.transkr")
    assert window.series.overview_action.isEnabled()
    dialog = window.series.show_overview()
    assert dialog is not None
    dialog.wait()
    assert dialog.table.rowCount() == 3
    assert dialog.overview is not None and len(dialog.overview.rows) == 3
    assert "3" in dialog.summary_label.text()
    status = dialog.table.item(1, dialog.table.STATUS)
    assert status is not None and status.text() == "Bez projektu"
    dialog.table.cellDoubleClicked.emit(2, 0)
    dialog.wait()
    assert _current(window) == "a3.mp3"
    dialog.close()


def test_overview_needs_series(qtbot, add_window) -> None:
    window = add_window(MainWindow())
    assert not window.series.overview_action.isEnabled()
    assert window.series.show_overview() is None


def _export_window(qtbot, add_window, tmp_path, target: str):
    folder = tmp_path / "seria"
    folder.mkdir()
    for name in ("a1.mp3", "a2.mp3", "a3.mp3"):
        shutil.copy(SAMPLE_MP3, folder / name)
    window = _window(qtbot, add_window, tmp_path / "none.zip", folder)
    window.series.folder_dialog()
    window.editor.setPlainText("pierwszy")
    window.series.open_next()
    window.editor.setPlainText("drugi")
    window.series.open_next()
    exporter = window.series.exporter
    summaries: list[tuple[str, str]] = []

    def accept(dialog) -> int:
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("txt"))
        dialog.target_combo.setCurrentIndex(dialog.target_combo.findData(target))
        return dialog.DialogCode.Accepted

    exporter.run_dialog = accept
    exporter.show_summary = lambda text, details: summaries.append((text, details))
    return window, folder, summaries


def test_export_series_to_folder(qtbot, add_window, tmp_path) -> None:
    window, folder, summaries = _export_window(qtbot, add_window, tmp_path, "folder")
    out = tmp_path / "out"
    out.mkdir()
    exporter = window.series.exporter
    exporter.choose_folder = lambda _start: out
    assert window.series.export_action.isEnabled()
    assert window.series.export_series()
    assert window.series.busy
    exporter.wait()
    assert sorted(p.name for p in out.iterdir()) == ["a1.txt", "a2.txt"]
    text, details = summaries[-1]
    assert "2" in text and "a3.mp3" in details
    # Drugi eksport do tego samego katalogu pyta o nadpisanie.
    asked: list[list[str]] = []

    def refuse(names: list[str]) -> bool:
        asked.append(names)
        return False

    exporter.confirm_overwrite = refuse
    assert not window.series.export_series()
    assert asked == [["a1.txt", "a2.txt"]]


def test_export_series_to_zip(qtbot, add_window, tmp_path) -> None:
    window, folder, summaries = _export_window(qtbot, add_window, tmp_path, "zip")
    archive = tmp_path / "seria.zip"
    window.series.exporter.choose_archive = lambda _start, _name: archive
    assert window.series.export_series()
    window.series.exporter.wait()
    with zipfile.ZipFile(archive) as handle:
        assert sorted(handle.namelist()) == ["a1.txt", "a2.txt"]
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".")) == []
    assert summaries


def test_cancelled_zip_export_writes_nothing(qtbot, add_window, tmp_path) -> None:
    window, folder, summaries = _export_window(qtbot, add_window, tmp_path, "zip")
    archive = tmp_path / "seria.zip"
    exporter = window.series.exporter
    exporter.choose_archive = lambda _start, _name: archive
    assert window.series.export_series()
    exporter.cancel()
    exporter.wait()
    assert not archive.exists()
    assert not summaries


def test_import_runs_in_background_with_progress(qtbot, add_window, tmp_path) -> None:
    window = _window(qtbot, add_window, _series_zip(tmp_path), tmp_path / "out")
    assert window.series.import_dialog()
    assert window.series.busy
    assert not window.series.importer.overlay.isHidden()
    # Drugi import nie rusza, dopóki trwa pierwszy.
    assert not window.series.import_dialog()
    window.series.importer.wait()
    assert not window.series.busy
    assert window.series.importer.overlay.isHidden()
    assert _current(window) == "w1.mp3"


def test_cancelled_import_leaves_no_partial_files(qtbot, add_window, tmp_path) -> None:
    window = _window(qtbot, add_window, _series_zip(tmp_path), tmp_path / "out")
    assert window.series.import_dialog()
    window.series.importer.cancel()
    window.series.importer.wait()
    assert not window.series.busy
    folder = tmp_path / "out" / "wywiady"
    leftovers = [p.name for p in folder.iterdir() if p.name.startswith(".")]
    assert leftovers == []
    assert _current(window) is None
