"""Podświetlanie części mowy w edytorze (zgłoszenie #35)."""

import pytest

from transkryptor.document.parts_of_speech import (
    AnalyserUnavailable,
    PartOfSpeech,
)
from transkryptor.ui.highlights import POS_LAYER
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.pos_highlights import POS_COLORS, PosHighlighter


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def highlighted(window: MainWindow) -> list[tuple[str, str]]:
    text = window.editor.plain_text()
    positions = window.editor.position_map()
    found = []
    for selection in window.editor.highlight_layer(POS_LAYER):
        cursor = selection.cursor
        start = positions.to_py(cursor.selectionStart())
        end = positions.to_py(cursor.selectionEnd())
        color = selection.format.background().color().name()
        found.append((text[start:end], color))
    return found


def test_selected_parts_are_highlighted_in_their_colors(window) -> None:
    window.editor.setPlainText("Kot szybko biegnie w ogrodzie.")
    window.parts_of_speech.set_part(PartOfSpeech.VERB, True)
    window.parts_of_speech.set_part(PartOfSpeech.ADVERB, True)
    assert highlighted(window) == [
        ("szybko", POS_COLORS[PartOfSpeech.ADVERB]),
        ("biegnie", POS_COLORS[PartOfSpeech.VERB]),
    ]
    window.parts_of_speech.set_part(PartOfSpeech.VERB, False)
    assert [word for word, _ in highlighted(window)] == ["szybko"]
    window.parts_of_speech.clear()
    assert highlighted(window) == []


def test_highlights_follow_text_edits(qtbot, window) -> None:
    window.editor.setPlainText("kot")
    window.parts_of_speech.set_part(PartOfSpeech.NOUN, True)
    window.editor.setPlainText("kot i pies")
    qtbot.waitUntil(lambda: len(highlighted(window)) == 2, timeout=2000)


def test_menu_offers_parts_of_speech(window) -> None:
    window.editor.setPlainText("Kot biegnie.")
    window.highlights_menu.refresh()
    menu = window.main_toolbar.highlights_menu
    (nouns,) = [a for a in menu.actions() if a.text() == "Rzeczowniki"]
    assert nouns.isCheckable() and not nouns.isChecked()
    nouns.setChecked(True)
    assert [word for word, _ in highlighted(window)] == ["Kot"]
    window.highlights_menu.refresh()
    (nouns,) = [a for a in menu.actions() if a.text() == "Rzeczowniki"]
    assert nouns.isChecked()
    (off,) = [a for a in menu.actions() if a.text().startswith("Wyłącz")]
    off.trigger()
    assert highlighted(window) == []


def test_missing_analyser_disables_the_feature(qtbot, window) -> None:
    def unavailable():
        raise AnalyserUnavailable("brak")

    messages: list[str] = []
    highlighter = PosHighlighter(
        window.editor, messages.append, window, tagger_factory=unavailable
    )
    highlighter.set_part(PartOfSpeech.NOUN, True)
    assert highlighter.selected == ()
    assert messages and "Morfeusz" in messages[0]
