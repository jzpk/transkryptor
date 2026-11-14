"""Okno „Pola tematyczne” (zgłoszenie #51)."""

import csv

import pytest
from PySide6.QtWidgets import QFileDialog

from transkryptor.document.parts_of_speech import AnalyserUnavailable
from transkryptor.document.speakers import INFORMANT, RESEARCHER, Speaker
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.themes_dialog import ThemesController, ThemesDialog


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def shown_dialog(controller: ThemesController) -> ThemesDialog:
    shown: list[ThemesDialog] = []

    def record(dialog: ThemesDialog) -> int:
        shown.append(dialog)
        return 0

    controller.run = record
    controller.action.trigger()
    return shown[0]


def test_dialog_lists_themes_and_exports_csv(window, tmp_path, monkeypatch) -> None:
    window.editor.setPlainText("Krowy na łące. Krowę pasłam. Był pogrzeb.")
    dialog = shown_dialog(window.themes)
    rows = {(str(theme), word): count for theme, word, count, _ in dialog.rows}
    assert rows[("Rolnictwo i praca w polu", "krowa")] == 2
    assert rows[("Śmierć i pogrzeb", "pogrzeb")] == 1
    assert dialog.empty_label.isHidden()

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "pola"), "")),
    )
    assert dialog.export(".csv")
    content = (tmp_path / "pola.csv").read_text(encoding="utf-8-sig").splitlines()
    table = list(csv.reader(content))
    assert table[0] == ["Pole tematyczne", "Słowo", "Wystąpienia", "Formy w tekście"]
    assert ["Rolnictwo i praca w polu", "krowa", "2", "krowy, krowę"] in table


def test_only_informants_count_when_speakers_are_assigned(window) -> None:
    window.speakers.apply_speakers(
        [Speaker("B", "Badacz", RESEARCHER), Speaker("I", "Informator", INFORMANT)]
    )
    window.editor.load_content("Czy był pogrzeb?\nKrowy pasłam.", [], {0: "B", 1: "I"})
    rows = shown_dialog(window.themes).rows
    assert {word for _, word, _, _ in rows} == {"krowa", "paść"}


def test_empty_text_has_no_rows(window) -> None:
    dialog = shown_dialog(window.themes)
    assert dialog.rows == ()
    assert not dialog.empty_label.isHidden()
    assert not dialog.csv_button.isEnabled()


def test_without_analyser_dictionary_forms_still_count(window) -> None:
    def unavailable():
        raise AnalyserUnavailable("brak")

    window.editor.setPlainText("krowa krowy")
    controller = ThemesController(
        window, lambda: window.document, lambda: "x", lemmatizer_factory=unavailable
    )
    dialog = shown_dialog(controller)
    assert [(word, count) for _, word, count, _ in dialog.rows] == [("krowa", 1)]


def test_action_is_in_export_menu(window) -> None:
    assert window.themes.action in window.main_toolbar.export_menu.actions()
