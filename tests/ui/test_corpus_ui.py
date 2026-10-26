"""Okno „Korpus”: wyszukiwanie w folderze, słownik form i eksport metryczek."""

import csv
from pathlib import Path

import pytest

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.document.project import ProjectState, save_project
from transkryptor.ui import corpus_dialog
from transkryptor.ui.corpus_dialog import CATALOG_TAB, FORMS_TAB, SCOPE_FOLDER
from transkryptor.ui.main_window import MainWindow

TEXT_A = "tak było\njag pamientam jak dziś"
TEXT_B = "jak to było"


@pytest.fixture
def folder(tmp_path) -> Path:
    save_project(
        ProjectState(
            text=TEXT_A,
            metadata={"signature": "A_1", "informant": "INF"},
            paragraph_speakers={0: "B", 1: "I"},
            anchors=(Anchor(9, len(TEXT_A), 2000, 5000, SEGMENT),),
        ),
        tmp_path / "A_1.transkr",
    )
    save_project(ProjectState(text=TEXT_B), tmp_path / "B_2.transkr")
    return tmp_path


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.show()
    return win


def open_corpus(window: MainWindow, folder: Path):
    dialog = window.corpus.open_dialog()
    dialog.set_folder(folder)
    return dialog


def search(dialog, query: str) -> list:
    dialog.query_edit.setText(query)
    dialog.run_search()
    return dialog.hits_table.hits


class TestCorpusSearch:
    def test_toolbar_action_opens_dialog_in_project_folder(
        self, window, folder
    ) -> None:
        assert window.session.open_project(folder / "A_1.transkr", confirm=False)
        window.corpus_action.trigger()
        dialog = window.corpus.dialog
        assert dialog is not None and dialog.isVisible()
        assert dialog.folder == folder
        assert dialog.summary_label.text() == "Projekty: 2"

    def test_search_lists_hits_from_all_projects(self, window, folder) -> None:
        dialog = open_corpus(window, folder)
        hits = search(dialog, "jak")
        assert [(hit.project.name, hit.match) for hit in hits] == [
            ("A_1", "jak"),
            ("B_2", "jak"),
        ]
        assert dialog.hits_table.rowCount() == 2
        assert dialog.hits_label.text() == "Trafienia: 2 w projektach: 2"
        assert hits[0].speaker == "I"
        assert hits[0].time_ms == (2000, 5000)

    def test_invalid_regex_is_reported(self, window, folder) -> None:
        dialog = open_corpus(window, folder)
        dialog.regex_check.setChecked(True)
        assert search(dialog, "(") == []
        assert "wyrażenie" in dialog.hits_label.text()

    def test_live_text_of_current_project_is_searched(self, window, folder) -> None:
        assert window.session.open_project(folder / "A_1.transkr", confirm=False)
        window.editor.setPlainText("jak jak\n" + TEXT_A)
        dialog = open_corpus(window, folder)
        hits = [hit for hit in search(dialog, "jak") if hit.project.name == "A_1"]
        assert len(hits) == 3

    def test_go_to_opens_other_project_and_selects_hit(self, window, folder) -> None:
        dialog = open_corpus(window, folder)
        search(dialog, "jak")
        dialog.hits_table.selectRow(1)
        dialog.go_to_selected()
        assert window.session.project_path == folder / "B_2.transkr"
        cursor = window.editor.textCursor()
        assert (cursor.selectionStart(), cursor.selectionEnd()) == (0, 3)

    def test_go_to_rejects_changed_text(self, window, folder) -> None:
        assert window.session.open_project(folder / "B_2.transkr", confirm=False)
        dialog = open_corpus(window, folder)
        search(dialog, "jak")
        window.editor.setPlainText("xyz to było")
        dialog.hits_table.selectRow(1)
        dialog.go_to_selected()
        assert "zmienił się" in dialog.status_label.text()

    def test_play_without_time_or_audio_explains(self, window, folder) -> None:
        dialog = open_corpus(window, folder)
        hits = search(dialog, "jak")
        assert not dialog.play_hit(hits[1])
        assert dialog.status_label.text() == (
            "Ten fragment nie jest powiązany z czasem nagrania."
        )
        assert not dialog.play_hit(hits[0])
        assert dialog.status_label.text() == "Nie znaleziono nagrania tego projektu."

    def test_locked_during_transcription(self, window, folder) -> None:
        dialog = open_corpus(window, folder)
        window._set_ui_locked(True)
        assert not dialog.isEnabled()
        assert not window.corpus_action.isEnabled()
        window._set_ui_locked(False)
        assert dialog.isEnabled()


class TestFormsTab:
    def test_current_project_forms_and_occurrences(self, window, folder) -> None:
        assert window.session.open_project(folder / "A_1.transkr", confirm=False)
        dialog = open_corpus(window, folder)
        dialog.tabs.setCurrentIndex(FORMS_TAB)
        forms = {entry.form: entry.count for entry in dialog.visible_forms()}
        assert forms == {
            "tak": 1,
            "było": 1,
            "jag": 1,
            "pamientam": 1,
            "jak": 1,
            "dziś": 1,
        }
        dialog.similar_check.setChecked(True)
        assert [entry.form for entry in dialog.visible_forms()] == ["jag", "jak", "tak"]
        assert dialog.select_form("jak")
        assert [hit.match for hit in dialog.occurrences_table.hits] == ["jak"]
        assert dialog.current_hit() is dialog.occurrences_table.hits[0]

    def test_folder_scope_and_filter(self, window, folder) -> None:
        dialog = open_corpus(window, folder)
        dialog.tabs.setCurrentIndex(FORMS_TAB)
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData(SCOPE_FOLDER))
        counts = {entry.form: entry.count for entry in dialog.visible_forms()}
        assert counts["jak"] == 2 and counts["było"] == 2
        dialog.forms_filter_edit.setText("ja")
        assert {entry.form for entry in dialog.visible_forms()} == {"jak", "jag"}

    def test_export_forms_csv(self, window, folder, monkeypatch) -> None:
        dialog = open_corpus(window, folder)
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData(SCOPE_FOLDER))
        target = folder / "formy.csv"
        monkeypatch.setattr(corpus_dialog, "ask_save_path", lambda *a: target)
        dialog.export_forms(".csv")
        rows = list(csv.reader(target.read_text(encoding="utf-8-sig").splitlines()))
        assert rows[0] == ["Forma", "Wystąpienia", "Projekty", "Formy podobne"]
        assert ["było", "2", "2", ""] in rows


class TestCatalogTab:
    def test_preview_and_exports(self, window, folder, monkeypatch) -> None:
        dialog = open_corpus(window, folder)
        dialog.tabs.setCurrentIndex(CATALOG_TAB)
        assert dialog.catalog_table.rowCount() == 2
        targets = iter([folder / "k.xlsx", folder / "k.csv", folder / "k.xml"])
        monkeypatch.setattr(corpus_dialog, "ask_save_path", lambda *a: next(targets))
        dialog.export_catalog(".xlsx")
        dialog.anonymize_check.setChecked(True)
        dialog.export_catalog(".csv")
        dialog.export_tei()
        assert (folder / "k.xlsx").stat().st_size > 0
        assert "INF" not in (folder / "k.csv").read_text(encoding="utf-8-sig")
        assert "teiCorpus" in (folder / "k.xml").read_text(encoding="utf-8")
        assert dialog.status_label.text() == "Zapisano „k.xml”."
