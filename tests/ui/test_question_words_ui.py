"""Okno „Słowa według pytań” (zgłoszenie #72)."""

import csv

import pytest
from PySide6.QtWidgets import QFileDialog

from transkryptor.document.parts_of_speech import AnalyserUnavailable, PartOfSpeech
from transkryptor.document.project import ProjectState, save_project
from transkryptor.document.questionnaire import QuestionMark
from transkryptor.document.speakers import INFORMANT, RESEARCHER, Speaker
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.question_words_controller import QuestionWordsController
from transkryptor.ui.question_words_dialog import QuestionWordsDialog

QUESTIONS = (
    "Jak wyglądało młócenie zboża?",
    "Gdzie przechowywano ziarno?",
    "Jak chowano zmarłych?",
)
TEXT = (
    "Jak wyglądało młócenie zboża?\n"
    "Młóciło się cepem na klepisku.\n"
    "Gdzie przechowywano ziarno?\n"
    "W sąsieku i w piecu.\n"
    "A jak to było, jak ktoś umarł?\n"
    "Trumnę robił stolarz."
)


@pytest.fixture
def window(add_window):
    window = add_window(MainWindow())
    window.speakers.apply_speakers(
        [Speaker("B", "Badacz", RESEARCHER), Speaker("I", "Informator", INFORMANT)]
    )
    speakers = {index: "B" if index % 2 == 0 else "I" for index in range(6)}
    window.editor.load_content(TEXT, [], speakers)
    window.asr_panel.set_questionnaire(QUESTIONS)
    return window


def shown_dialog(controller: QuestionWordsController) -> QuestionWordsDialog:
    controller.run = lambda dialog: None
    controller.action.trigger()
    assert controller.dialog is not None
    return controller.dialog


def words(dialog: QuestionWordsDialog, number: int) -> list[str]:
    section = next(s for s in dialog.report.sections if s.number == number)
    return [word.lemma for word in section.words]


def test_action_is_in_export_menu(window) -> None:
    action = window.analysis.question_words.action
    assert action in window.main_toolbar.export_menu.actions()


def test_dialog_splits_nouns_by_question(window) -> None:
    dialog = shown_dialog(window.analysis.question_words)
    assert words(dialog, 1) == ["cep", "klepisko"]
    assert "sąsiek" in words(dialog, 2)
    # Pytanie 3 zadano innymi słowami - jest na liście nieodnalezionych,
    # a jego odpowiedzi liczą się do pytania 2.
    assert [q.number for q in dialog.report.unlocated] == [3]
    assert "trumna" in words(dialog, 2)
    assert len(dialog.cards.cards) == 2
    assert len(dialog.cards.unlocated_buttons) == 1


def test_parts_of_speech_and_mode_change_the_list(window) -> None:
    dialog = shown_dialog(window.analysis.question_words)
    dialog.set_part(PartOfSpeech.VERB, True)
    assert "młócić" in words(dialog, 1)
    exact_tip = dialog.mode_info.toolTip()
    dialog.set_mode_full(True)
    assert dialog.mode_info.toolTip() != exact_tip
    assert "piec" in words(dialog, 2)
    # Ostatniej części mowy nie da się odznaczyć.
    dialog.set_part(PartOfSpeech.VERB, False)
    dialog.set_part(PartOfSpeech.NOUN, False)
    assert dialog.part_buttons[PartOfSpeech.NOUN].isChecked()


def test_marking_a_paragraph_is_saved_in_the_project(window) -> None:
    controller = window.analysis.question_words
    dialog = shown_dialog(controller)
    controller.mark(2, 4)
    assert window.asr_panel.question_marks() == (
        QuestionMark(2, "A jak to było, jak ktoś umarł?"),
    )
    assert window.session.has_unsaved_work
    # „stolarz” bez kontekstu to też czasownik („stolarzyć”) - liczy się
    # tylko w pełniejszej liście.
    assert words(dialog, 3) == ["trumna"]
    assert not dialog.report.unlocated
    state = window.session.capture_state()
    assert state.asr_context.question_marks == window.asr_panel.question_marks()
    controller.unmark(2)
    assert window.asr_panel.question_marks() == ()
    assert [q.number for q in dialog.report.unlocated] == [3]


def test_mark_from_editor_cursor(window) -> None:
    controller = window.analysis.question_words
    shown_dialog(controller)
    controller.go_to(4)
    assert window.editor.textCursor().blockNumber() == 4
    controller.mark_cursor(2)
    assert window.asr_panel.question_marks()[0].question == 2


def test_new_questionnaire_clears_marks(window) -> None:
    window.asr_panel.set_question_marks((QuestionMark(2, "A jak to było?"),))
    window.asr_panel.transcription.questionnaire_box.set_questions(QUESTIONS[:1])
    assert window.asr_panel.question_marks() == ()


def test_export_csv(window, tmp_path, monkeypatch) -> None:
    dialog = shown_dialog(window.analysis.question_words)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "slowa"), "")),
    )
    assert dialog.export(".csv")
    content = (tmp_path / "slowa.csv").read_text(encoding="utf-8-sig").splitlines()
    table = list(csv.reader(content))
    assert table[0][:4] == ["Nr", "Pytanie", "Słowo", "Część mowy"]
    assert table[1][:4] == ["1", QUESTIONS[0], "cep", "rzeczownik"]


def test_joined_project_adds_answers(window, tmp_path) -> None:
    # Projekt bez własnego kwestionariusza dzieli się pytaniami bieżącego.
    path = tmp_path / "inny.transkr"
    save_project(
        ProjectState(
            text="Jak wyglądało młócenie zboża?\nCepem.",
            speakers=(Speaker("B", "", RESEARCHER), Speaker("I", "Anna", INFORMANT)),
            paragraph_speakers={0: "B", 1: "I"},
        ),
        path,
    )
    controller = window.analysis.question_words
    dialog = shown_dialog(controller)
    assert controller.join_projects([path, path]) == 1
    cep = next(w for w in dialog.report.sections[0].words if w.lemma == "cep")
    assert cep.count == 2
    assert set(cep.speakers) == {"Informator", "Anna"}


def test_without_analyser_the_list_is_empty(window) -> None:
    def unavailable():
        raise AnalyserUnavailable("brak")

    controller = QuestionWordsController(
        window,
        window.session,
        window.asr_panel,
        window.editor,
        window.sync,
        analyser_factory=unavailable,
    )
    dialog = shown_dialog(controller)
    assert dialog.report.sections == ()


def test_locked_while_transcribing(window) -> None:
    controller = window.analysis.question_words
    window._set_ui_locked(True)
    assert not controller.action.isEnabled()
    window._set_ui_locked(False)
    assert controller.action.isEnabled()
