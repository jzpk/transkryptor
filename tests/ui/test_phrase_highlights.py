"""Trwałe podświetlanie fraz (zgłoszenie #36)."""

import pytest

from transkryptor.document.search import SearchOptions
from transkryptor.ui.highlights import PHRASE_LAYER
from transkryptor.ui.main_window import MainWindow


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def highlighted(window: MainWindow) -> list[str]:
    text = window.editor.plain_text()
    positions = window.editor.position_map()
    return sorted(
        text[
            positions.to_py(sel.cursor.selectionStart()) : positions.to_py(
                sel.cursor.selectionEnd()
            )
        ]
        for sel in window.editor.highlight_layer(PHRASE_LAYER)
    )


def highlight_from_bar(window: MainWindow, query: str) -> None:
    window.search_actions["find"].trigger()
    window.search_bar.find_edit.setText(query)
    window.search_bar.highlight_button.click()


def test_highlight_button_adds_phrase_that_survives_closing_search(window) -> None:
    window.editor.setPlainText("Ala ma kota, a kot ma Alę.")
    assert not window.search_bar.highlight_button.isEnabled()
    highlight_from_bar(window, "ma")
    window.search.close()
    assert highlighted(window) == ["ma", "ma"]
    assert "2" in window.statusBar().currentMessage()


def test_highlights_follow_text_edits(qtbot, window) -> None:
    window.editor.setPlainText("kot")
    window.phrases.add("kot", SearchOptions())
    window.editor.setPlainText("kot i kot, i jeszcze kot")
    qtbot.waitUntil(lambda: len(highlighted(window)) == 3, timeout=2000)


def test_phrases_get_different_colors_and_options_apply(window) -> None:
    window.editor.setPlainText("Kot kotek kot")
    first = window.phrases.add("kot", SearchOptions(whole_words=True))
    second = window.phrases.add("kotek", SearchOptions())
    assert first is not None and second is not None
    assert first.color != second.color
    assert window.phrases.count(first) == 2
    assert highlighted(window) == ["Kot", "kot", "kotek"]


def test_duplicate_and_invalid_phrases_are_rejected(window) -> None:
    window.editor.setPlainText("kot")
    assert window.phrases.add("kot", SearchOptions()) is not None
    assert window.phrases.add("kot", SearchOptions()) is None
    assert window.phrases.add("(", SearchOptions(regex=True)) is None
    assert len(window.phrases.phrases) == 1


def test_menu_lists_phrases_and_unchecking_removes(window) -> None:
    window.editor.setPlainText("kot pies kot")
    window.phrases.add("kot", SearchOptions())
    window.phrases.add("pies", SearchOptions())
    menu = window.main_toolbar.highlights_menu
    window.highlights_menu.refresh()
    texts = [action.text() for action in menu.actions()]
    assert "„kot” (2)" in texts
    assert "„pies” (1)" in texts
    (kot,) = [action for action in menu.actions() if action.text() == "„kot” (2)"]
    kot.setChecked(False)
    assert highlighted(window) == ["pies"]

    window.highlights_menu.refresh()
    (clear,) = [a for a in menu.actions() if a.text().startswith("Usuń wszystkie")]
    clear.trigger()
    assert highlighted(window) == []
    window.highlights_menu.refresh()
    assert "Brak podświetlonych fraz" in [a.text() for a in menu.actions()]


def test_menu_add_opens_search_bar(window) -> None:
    window.highlights_menu.refresh()
    (add,) = [
        a
        for a in window.main_toolbar.highlights_menu.actions()
        if a.text() == "Podświetl frazę…"
    ]
    add.trigger()
    assert window.search.is_open()
