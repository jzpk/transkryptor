"""Sprawdzenie gotowej transkrypcji według reguł szkicu (zgłoszenie #62)."""

from transkryptor.asr.draft_style import DraftStyle
from transkryptor.asr.qa_layout import ends_with_question
from transkryptor.asr.recheck import (
    STYLE_CODE,
    question_answer_speakers,
    style_suggestions,
)

ABBREVIATIONS = DraftStyle(expand_abbreviations=True, lowercase_plain=False)
SPEECH = DraftStyle(expand_abbreviations=True, lowercase_plain=True)


def _apply(text, suggestions):
    for suggestion in sorted(suggestions, key=lambda s: s.start, reverse=True):
        assert text[suggestion.start : suggestion.end] == suggestion.original
        text = (
            text[: suggestion.start] + suggestion.replacement + text[suggestion.end :]
        )
    return text


def test_abbreviation_becomes_a_suggestion_for_its_word() -> None:
    text = "Był tam np. młyn."
    [suggestion] = style_suggestions(text, ABBREVIATIONS)
    assert suggestion.code == STYLE_CODE
    assert suggestion.original == "np."
    assert suggestion.replacement == "na przykład"
    assert suggestion.word == "np."
    assert text[suggestion.word_start :].startswith("np.")
    assert "Skróty" in suggestion.message
    assert _apply(text, [suggestion]) == "Był tam na przykład młyn."


def test_suggestions_rebuild_the_draft_style_paragraph_by_paragraph() -> None:
    text = "Tam był np. młyn, wiatrak. Kto to zrobił?\nJa, sąsiad."
    suggestions = style_suggestions(text, SPEECH)
    assert _apply(text, suggestions) == (
        "tam był na przykład młyn wiatrak kto to zrobił?\nja sąsiad"
    )
    assert all(s.original for s in suggestions)
    assert {s.message.split(":")[0] for s in suggestions} == {
        "Skróty w pełnym brzmieniu",
        "Zapis mowy",
    }


def test_text_already_in_draft_style_has_no_suggestions() -> None:
    assert style_suggestions("tam był młyn kto to zrobił?\nja", SPEECH) == []
    assert style_suggestions("Był np. młyn.", DraftStyle(False, False)) == []


def test_questions_go_to_the_researcher_and_answers_to_the_informant() -> None:
    text = "Gdzie stał młyn?\nPrzy rzece.\n\nCo nie?\nTo dawno było, prawda?"
    speakers = question_answer_speakers(text, {4: "X"}, ends_with_question, "B", "I")
    assert speakers == {0: "B", 1: "I", 3: "I"}
