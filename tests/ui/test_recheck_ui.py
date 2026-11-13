"""„Sprawdź tekst” - gotowa transkrypcja według reguł szkicu (zgłoszenie #62)."""

from dataclasses import replace

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox, QToolButton

from transkryptor.asr.recheck import STYLE_CODE
from transkryptor.ui.main_window import MainWindow

OLD_TEXT = "Był np. młyn.\nGdzie stał wiatrak?\nPrzy rzece, za wsią."


@pytest.fixture
def window(add_window, monkeypatch):
    window = add_window(MainWindow())
    asked: list[str] = []
    window.asked = asked

    def no(_parent, _title, text, *_args, **_kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(no))
    window.editor.setPlainText(OLD_TEXT)
    return window


def _answer_yes(monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )


def test_check_lists_suggestions_without_changing_the_text(window) -> None:
    window.asr_panel.review.recheck_button.click()

    assert window.editor.plain_text() == OLD_TEXT
    items = window.review.items
    assert items
    assert not any(item.applied for item in items)
    style = [item for item in items if item.suggestion.code == STYLE_CODE]
    assert any(item.suggestion.replacement == "na przykład" for item in style)
    assert window.findChild(QToolButton, "asr_review_toggle").isChecked()
    assert "propozycji" in window.statusBar().currentMessage()


def test_style_suggestion_applies_to_its_word(window) -> None:
    window.asr_panel.review.recheck_button.click()
    index = next(
        i
        for i, item in enumerate(window.review.items)
        if item.suggestion.original == "np."
    )
    window.review.apply(index)
    assert window.editor.plain_text().startswith("Był na przykład młyn.")


def test_style_follows_the_asr_settings(window) -> None:
    current = window.settings_store.current
    window.settings_store.save(
        replace(
            current,
            asr=replace(current.asr, expand_abbreviations=False, lowercase_plain=False),
        )
    )
    window.asr_panel.review.recheck_button.click()
    assert not any(item.suggestion.code == STYLE_CODE for item in window.review.items)


def test_rule_matches_stay_suggestions_even_for_auto_applied_rules(window) -> None:
    window.editor.setPlainText("on będzie tu")
    assert window.asr_panel.selected_rule_codes()
    window.asr_panel.review.recheck_button.click()
    rules = [i for i in window.review.items if i.suggestion.code != STYLE_CODE]
    assert rules
    assert not any(item.applied for item in rules)
    assert window.editor.plain_text() == "on będzie tu"


def test_words_with_superscript_get_no_suggestions(window) -> None:
    cursor = window.editor.textCursor()
    start = OLD_TEXT.index("np")
    cursor.setPosition(start)
    cursor.setPosition(start + 1, QTextCursor.MoveMode.KeepAnchor)
    window.editor.setTextCursor(cursor)
    window.editor.toggle_superscript()
    window.asr_panel.review.recheck_button.click()
    assert not any(
        item.suggestion.start <= start < item.suggestion.end
        for item in window.review.items
    )


def test_paragraphs_without_speaker_get_question_answer_speakers(
    window, monkeypatch
) -> None:
    _answer_yes(monkeypatch)
    window.asr_panel.review.recheck_button.click()
    assert window.editor.paragraph_speakers() == {0: "I", 1: "B", 2: "I"}
    window.editor.undo()
    assert window.editor.paragraph_speakers() == {}
    assert window.editor.plain_text() == OLD_TEXT


def test_declined_speakers_change_nothing(window) -> None:
    window.asr_panel.review.recheck_button.click()
    assert len(window.asked) == 1
    assert "3" in window.asked[0]
    assert window.editor.paragraph_speakers() == {}


def test_paragraphs_with_speakers_are_not_asked_about(window) -> None:
    cursor = window.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    window.editor.setTextCursor(cursor)
    window.editor.set_paragraph_speaker("I")
    window.asr_panel.review.recheck_button.click()
    assert window.asked == []


def test_empty_editor_is_reported(window) -> None:
    window.editor.setPlainText("")
    window.asr_panel.review.recheck_button.click()
    assert window.review.items == []
    assert window.asked == []
    assert "pusty" in window.statusBar().currentMessage()
