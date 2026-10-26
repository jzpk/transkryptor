"""Okno „Korpus”: wyszukiwanie w folderze, słownik form i eksport metryczek."""

import csv
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.document.project import ProjectState, save_project
from transkryptor.ui import corpus_dialog
from transkryptor.ui.corpus_dialog import (
    BUSY_DELAY_MS,
    CATALOG_TAB,
    FORMS_TAB,
    SCOPE_FOLDER,
)
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
    dialog.wait()
    dialog.set_folder(folder)
    dialog.wait()
    return dialog


def search(dialog, query: str) -> list:
    dialog.query_edit.setText(query)
    dialog.run_search()
    dialog.wait()
    return dialog.hits_table.hits


class TestCorpusSearch:
    def test_toolbar_action_opens_dialog_in_project_folder(
        self, window, folder
    ) -> None:
        assert window.session.open_project(folder / "A_1.transkr", confirm=False)
        window.corpus_action.trigger()
        dialog = window.corpus.dialog
        assert dialog is not None and dialog.isVisible()
        dialog.wait()
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
        dialog.wait()
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
        dialog.wait()
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData(SCOPE_FOLDER))
        dialog.wait()
        counts = {entry.form: entry.count for entry in dialog.visible_forms()}
        assert counts["jak"] == 2 and counts["było"] == 2
        dialog.forms_filter_edit.setText("ja")
        assert {entry.form for entry in dialog.visible_forms()} == {"jak", "jag"}

    def test_export_forms_csv(self, window, folder, monkeypatch) -> None:
        dialog = open_corpus(window, folder)
        dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData(SCOPE_FOLDER))
        dialog.wait()
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


class TestShortcut:
    def test_default_shortcut_opens_corpus(self, window) -> None:
        assert window.corpus_action.shortcut().toString() == "Ctrl+Shift+F"
        assert "Ctrl+Shift+F" in window.corpus_action.toolTip()
        assert window.shortcut_actions["project.corpus"] is window.corpus_action


class TestBusyOverlay:
    @pytest.fixture
    def blocked(self, window, folder):
        """Okno korpusu z pracą w tle, która trwa do ``release.set()``."""
        dialog = open_corpus(window, folder)
        release = threading.Event()
        results: list[object] = []

        def work(progress):
            progress(1, 4)
            while not release.wait(0.01):
                if not progress(1, 4):
                    return "przerwane"
            return "gotowe"

        assert dialog._run("Praca", work, results.append)
        yield dialog, release, results
        release.set()
        dialog.wait()

    def test_overlay_with_spinner_blocks_input_until_done(
        self, qtbot, window, blocked
    ) -> None:
        dialog, release, results = blocked
        assert dialog.busy
        # Druga praca nie startuje, póki trwa pierwsza.
        assert not dialog.run_search()
        qtbot.wait(BUSY_DELAY_MS + 100)
        assert dialog.overlay.isVisible()
        assert dialog.overlay.spinner.is_spinning()
        assert dialog.overlay.title_label.text() == "Praca"
        assert dialog.overlay.detail_label.text() == "Projekty: 1 z 4"
        assert dialog._cover is not None and dialog._cover.isVisible()
        # Klawiatura i skróty nie docierają do okien.
        press = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a"
        )
        QApplication.sendEvent(dialog.query_edit, press)
        assert dialog.query_edit.text() == ""
        # Zamknięcie okien czeka na koniec pracy.
        assert not dialog.close()
        assert dialog.isVisible()
        release.set()
        dialog.wait()
        assert results == ["gotowe"]
        assert not dialog.busy
        assert not dialog.overlay.isVisible()
        assert not dialog._cover.isVisible()
        QApplication.sendEvent(dialog.query_edit, press)
        assert dialog.query_edit.text() == "a"

    def test_cancel_discards_result(self, qtbot, blocked) -> None:
        dialog, _release, results = blocked
        qtbot.wait(BUSY_DELAY_MS + 100)
        qtbot.mouseClick(dialog.overlay.cancel_button, Qt.MouseButton.LeftButton)
        dialog.wait()
        assert results == []
        assert not dialog.busy
        assert dialog.status_label.text() == "Przerwano - wyniki się nie zmieniły."

    def test_main_window_waits_for_corpus_work(self, window, blocked) -> None:
        assert not window.close()
        assert window.isVisible()
