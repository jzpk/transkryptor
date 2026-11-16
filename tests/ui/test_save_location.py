"""Wspólny folder zapisu projektu, eksportu i paczki (zgłoszenie #67)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

from transkryptor.settings import ProjectSettings, Settings
from transkryptor.ui import save_location
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog


@pytest.fixture
def window(add_window) -> MainWindow:
    return add_window(MainWindow())


def record_save_dialog(monkeypatch, answer: Path | None) -> list[str]:
    """Okno zapisu zwraca ``answer``; lista zbiera proponowane ścieżki."""
    proposed: list[str] = []

    def fake(_parent, _title, default, *_args, **_kwargs):
        proposed.append(default)
        return (str(answer) if answer is not None else "", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    return proposed


def test_default_folder_is_created_on_first_save(window, monkeypatch) -> None:
    default = save_location.default_save_dir()
    proposed = record_save_dialog(monkeypatch, None)
    window.editor.setPlainText("tekst")
    window.session.save_project_as()
    assert default.is_dir()
    assert Path(proposed[0]).parent == default


def test_export_goes_next_to_saved_project(window, monkeypatch, tmp_path) -> None:
    project = tmp_path / "wywiady" / "AdK_1954.transkr"
    project.parent.mkdir()
    window.editor.setPlainText("tekst")
    record_save_dialog(monkeypatch, project)
    assert window.session.save_project_as()
    proposed = record_save_dialog(monkeypatch, None)
    window.exporter.export()
    assert Path(proposed[0]).parent == project.parent


def test_chosen_folder_is_remembered(window, monkeypatch, tmp_path) -> None:
    """Zmieniony folder nie wraca do poprzedniego przy kolejnym zapisie."""
    target = tmp_path / "moje" / "eksport.docx"
    target.parent.mkdir()
    window.editor.setPlainText("tekst")
    record_save_dialog(monkeypatch, target)
    window.exporter.export()
    assert window.settings_store.current.project.save_dir == str(target.parent)
    proposed = record_save_dialog(monkeypatch, None)
    window.session.save_project_as()
    assert Path(proposed[0]).parent == target.parent


def test_chosen_folder_overrides_project_folder(window, monkeypatch, tmp_path) -> None:
    """Folder z ustawień wygrywa także z folderem otwartego projektu."""
    chosen = tmp_path / "wybrany"
    chosen.mkdir()
    project = tmp_path / "gdzie-indziej" / "AdK_1954.transkr"
    project.parent.mkdir()
    window.editor.setPlainText("tekst")
    record_save_dialog(monkeypatch, project)
    assert window.session.save_project_as()
    window.settings_store.save(Settings(project=ProjectSettings(save_dir=str(chosen))))
    proposed = record_save_dialog(monkeypatch, None)
    window.exporter.export()
    window.session.save_project_as()
    assert [Path(path).parent for path in proposed] == [chosen, chosen]


def test_saving_in_default_folder_clears_choice(window, monkeypatch, tmp_path) -> None:
    window.settings_store.save(
        Settings(project=ProjectSettings(save_dir=str(tmp_path)))
    )
    default = save_location.default_save_dir()
    default.mkdir(parents=True, exist_ok=True)
    window.editor.setPlainText("tekst")
    record_save_dialog(monkeypatch, default / "eksport.docx")
    window.exporter.export()
    assert window.settings_store.current.project.save_dir == ""


def test_missing_save_folder_falls_back_to_default(
    window, monkeypatch, tmp_path
) -> None:
    gone = tmp_path / "usuniety"
    window.settings_store.save(Settings(project=ProjectSettings(save_dir=str(gone))))
    proposed = record_save_dialog(monkeypatch, None)
    window.session.save_project_as()
    assert Path(proposed[0]).parent == save_location.default_save_dir()


def test_settings_page_round_trips_save_folder(window, tmp_path) -> None:
    custom = Settings(project=ProjectSettings(save_dir=str(tmp_path)))
    dialog = SettingsDialog(custom, window)
    assert dialog.project_page.save_dir_edit.text() == str(tmp_path)
    assert dialog.settings() == custom
