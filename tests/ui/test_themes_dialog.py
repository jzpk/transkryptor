"""Okno „Pola tematyczne” (zgłoszenia #51, #71)."""

import csv

import pytest
from PySide6.QtWidgets import QFileDialog

from transkryptor.document.parts_of_speech import AnalyserUnavailable
from transkryptor.document.project import ProjectState, save_project
from transkryptor.document.speakers import INFORMANT, RESEARCHER, Speaker
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.themes_controller import ThemesController
from transkryptor.ui.themes_dialog import ThemesDialog


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
    controller = ThemesController(window, lambda: window.document, lambda: "x")
    dialog = shown_dialog(controller)
    rows = {(str(row[0]), row[1]): row[2] for row in dialog.rows}
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
    assert table[0] == [
        "Pole tematyczne",
        "Słowo",
        "Wystąpienia",
        "Formy w tekście",
        "Informatorzy",
    ]
    assert ["Rolnictwo i praca w polu", "krowa", "2", "krowy, krowę", "x"] in table


def test_only_informants_count_when_speakers_are_assigned(window) -> None:
    window.speakers.apply_speakers(
        [Speaker("B", "Badacz", RESEARCHER), Speaker("I", "Informator", INFORMANT)]
    )
    window.editor.load_content("Czy był pogrzeb?\nKrowy pasłam.", [], {0: "B", 1: "I"})
    rows = shown_dialog(window.themes).rows
    assert {row[1] for row in rows} == {"krowa", "paść"}
    assert {row[4] for row in rows} == {"Informator"}


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
    assert [row[1:3] for row in dialog.rows] == [("krowa", 1)]


def test_action_is_in_export_menu(window) -> None:
    assert window.themes.action in window.main_toolbar.export_menu.actions()


def informant_project(path, text: str, label: str) -> None:
    speakers = (Speaker("B", "", RESEARCHER), Speaker("I", label, INFORMANT))
    lines = text.count("\n") + 1
    assignments = {index: "I" for index in range(lines)}
    save_project(
        ProjectState(text=text, speakers=speakers, paragraph_speakers=assignments),
        path,
    )


def test_joined_transcriptions_show_which_informants_used_a_word(
    window, tmp_path, monkeypatch
) -> None:
    window.speakers.apply_speakers(
        [Speaker("B", "", RESEARCHER), Speaker("I", "Anna", INFORMANT)]
    )
    window.editor.load_content("Krowy pasłam.", [], {0: "I"})
    informant_project(tmp_path / "drugi.transkr", "Krowa i pogrzeb.", "Jan")
    informant_project(tmp_path / "trzeci.transkr", "Krowę doiłam.", "")
    dialog = shown_dialog(window.themes)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(
            lambda *a, **k: (
                [str(tmp_path / "drugi.transkr"), str(tmp_path / "trzeci.transkr")],
                "",
            )
        ),
    )
    dialog.add_button.click()
    rows = {row[1]: row for row in dialog.rows}
    assert rows["krowa"][2] == 3
    assert rows["krowa"][4] == "Anna, Jan, I (trzeci)"
    assert rows["pogrzeb"][4] == "Jan"
    assert "drugi, trzeci" in dialog.sources_label.text()

    assert dialog.select_field("funeral")
    assert dialog.header == ("Słowo", "Wystąpienia", "Formy w tekście", "Informatorzy")
    assert dialog.rows == (("pogrzeb", 1, "pogrzeb", "Jan"),)


def test_joining_skips_repeated_and_unreadable_projects(
    window, tmp_path, monkeypatch
) -> None:
    informant_project(tmp_path / "drugi.transkr", "Krowa.", "Jan")
    (tmp_path / "zepsuty.transkr").write_text("{", encoding="utf-8")
    errors: list[str] = []
    monkeypatch.setattr(
        "transkryptor.ui.themes_controller.show_error",
        lambda _parent, title, _error: errors.append(title),
    )
    dialog = shown_dialog(window.themes)
    paths = [tmp_path / "drugi.transkr", tmp_path / "zepsuty.transkr"]
    assert window.themes.join_projects(dialog, paths) == 1
    assert window.themes.join_projects(dialog, paths[:1]) == 0
    assert errors == ["Nie udało się dołączyć transkrypcji"]
    assert [row[1] for row in dialog.rows] == ["krowa"]
