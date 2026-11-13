"""Układ szkicu „pytanie - odpowiedź” w oknie (zgłoszenie #41)."""

import pytest

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.ui.main_window import MainWindow

TEXT = " Imię i nazwisko? Krystyna Adamek. Zajęcie? Rolnik, nie? Tak."


@pytest.fixture
def window(add_window):
    window = add_window(MainWindow())
    for box in window.asr_panel.review.rule_checkboxes.values():
        box.setChecked(False)
    return window


def draft() -> TranscriptionResult:
    segment = SegmentResult(0.0, 10.0, TEXT, 0.9)
    return TranscriptionResult(text=TEXT.strip(), language="pl", segments=(segment,))


def test_checkbox_lays_out_questions_and_answers(window) -> None:
    check = window.asr_panel.transcription.qa_layout_check
    assert not check.isChecked()
    check.setChecked(True)
    assert window.settings_store.current.asr.qa_layout
    # Podział według głosu nie jest wtedy liczony.
    assert not window.asr_panel.decoding_options().diarize

    window.asr.insert_draft(draft())
    lines = window.editor.plain_text().split("\n")
    assert [line.split("] ", 1)[1] for line in lines] == [
        "imię i nazwisko?",
        "Krystyna Adamek",
        "zajęcie?",
        "rolnik nie? tak",
    ]
    keys = window.editor.paragraph_speakers(window.editor.plain_text())
    assert keys == {0: "B", 1: "I", 2: "B", 3: "I"}


def test_without_layout_draft_keeps_lines(window) -> None:
    window.asr.insert_draft(draft())
    assert window.editor.plain_text().count("\n") == 0
