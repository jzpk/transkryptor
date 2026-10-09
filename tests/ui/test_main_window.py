"""Testy głównego okna: ACC-01..07 i ACC-23..25 na poziomie interfejsu."""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from transkryptor.i18n import tr
from transkryptor.settings import NotationSettings
from transkryptor.ui.main_window import MainWindow


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def set_ellipsis_style(window: MainWindow, style: str) -> None:
    current = window.settings_store.current
    window.settings_store.save(
        replace(current, notation=NotationSettings(ellipsis_style=style))
    )


def type_text(qtbot, window: MainWindow, text: str) -> None:
    """Wpisuje tekst do edytora, używając keyClicks dla ASCII i wklejania dla polskich znaków.

    Offscreen Qt nie mapuje klawiszy Unicode, dlatego znaki spoza ASCII są
    wstawiane bezpośrednio — test nadal sprawdza, że edytor je zachowuje.
    """
    window.editor.setFocus()
    ascii_part = ""
    for char in text:
        if ord(char) < 128:
            ascii_part += char
        else:
            if ascii_part:
                qtbot.keyClicks(window.editor, ascii_part)
                ascii_part = ""
            window.editor.insertPlainText(char)
    if ascii_part:
        qtbot.keyClicks(window.editor, ascii_part)


def panel_texts(window: MainWindow) -> list[str]:
    return [
        window.warnings_panel.item(i).text()
        for i in range(window.warnings_panel.count())
    ]


class TestAcc01PolishText:
    def test_polish_characters_and_hyphens_are_preserved(self, qtbot, window) -> None:
        """ACC-01: tekst z polskimi znakami i łącznikami bez zamiany i utraty."""
        type_text(qtbot, window, "pamientam uóna zmar-zły jeż...")
        assert window.editor.toPlainText() == "pamientam uóna zmar-zły jeż..."
        assert window.document.text == "pamientam uóna zmar-zły jeż..."


class TestAcc02SuperscriptShortcut:
    @pytest.mark.parametrize("char_index", [5, 8])  # nosowe „n” i końcowe „m”
    def test_shortcut_formats_selection(self, qtbot, window, char_index: int) -> None:
        """ACC-02: Ctrl+Shift+Up nadaje indeks górny zaznaczeniu."""
        window.editor.setPlainText("pamientam")
        cursor = window.editor.textCursor()
        cursor.setPosition(char_index)
        cursor.setPosition(char_index + 1, QTextCursor.MoveMode.KeepAnchor)
        window.editor.setTextCursor(cursor)
        window.superscript_action.trigger()
        assert window.document.superscript_ranges == [(char_index, char_index + 1)]
        # Pozostały tekst bez formatu:
        assert len(window.document.superscript_ranges) == 1


class TestAcc03MarkersViaShortcutsAndButtons:
    def test_pause_action_inserts_exact_marker(self, qtbot, window) -> None:
        """ACC-03: pauza w stylu z ustawień — domyślnie ` … `, potem ` ... `."""
        type_text(qtbot, window, "rzeczy")
        window.marker_actions["pause"].trigger()
        assert window.editor.toPlainText() == "rzeczy … "
        set_ellipsis_style(window, "ascii")
        window.marker_actions["pause"].trigger()
        assert window.editor.toPlainText() == "rzeczy …  ... "
        assert "..." in window.marker_actions["pause"].toolTip()

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("oddity", "(!)"),
            ("doubt", "(?)"),
            ("omitted", "[…?]"),
            ("aside", "[...]"),
        ],
    )
    def test_marker_actions(self, qtbot, window, key, expected) -> None:
        """Skróty i przyciski markerów są podpięte do akcji i wstawiają tekst."""
        window.marker_actions[key].trigger()
        assert window.editor.toPlainText() == expected
        assert window.marker_actions[key].shortcut().toString()

    @pytest.mark.parametrize("key", ["omitted", "aside"])
    def test_toolbar_label_keeps_ellipsis(self, window, key) -> None:
        """Napis przycisku pokazuje pełny marker, z wielokropkiem w nawiasie."""
        action = window.marker_actions[key]
        assert action.iconText() == action.text()


class TestWarningsPanel:
    """ACC-04..07: panel ostrzeżeń pokazuje wyniki walidatora.

    Scenariusze ACC-04/05 zapisują wielokropek trzema kropkami, więc testy
    wybierają ten styl — inaczej doszłyby wskazówki VAL-05.
    """

    @pytest.fixture(autouse=True)
    def ascii_style(self, window) -> None:
        set_ellipsis_style(window, "ascii")

    def type_and_validate(self, qtbot, window, text: str) -> None:
        type_text(qtbot, window, text)
        window.run_validation_now()

    def test_acc04_cut_off_words_show_no_warnings(self, qtbot, window) -> None:
        self.type_and_validate(qtbot, window, "jeż... kam... kamionka")
        assert window.warnings_panel.warning_count() == 0
        assert panel_texts(window) == [tr("warnings.empty")]

    def test_acc05_pause_without_following_space(self, qtbot, window) -> None:
        self.type_and_validate(qtbot, window, "rzeczy ...bo")
        assert window.warnings_panel.warning_count() == 1
        assert "VAL-01" in panel_texts(window)[0]

    def test_acc06_unclosed_aside(self, qtbot, window) -> None:
        self.type_and_validate(qtbot, window, "trzea [świnię")
        assert window.warnings_panel.warning_count() == 1
        assert "VAL-02" in panel_texts(window)[0]

    def test_acc07_wrong_omitted_marker(self, qtbot, window) -> None:
        self.type_and_validate(qtbot, window, "odstraszy […] inne ptaki")
        assert window.warnings_panel.warning_count() == 1
        assert "VAL-03" in panel_texts(window)[0]

    def test_debounced_validation_updates_panel(self, qtbot, window) -> None:
        type_text(qtbot, window, "rzeczy ...bo")
        qtbot.waitSignal(window._validation_timer.timeout, timeout=2000)
        qtbot.waitUntil(
            lambda: window.warnings_panel.warning_count() == 1, timeout=1000
        )

    def test_clicking_warning_moves_cursor_to_range(self, qtbot, window) -> None:
        self.type_and_validate(qtbot, window, "rzeczy ...bo")
        item = window.warnings_panel.item(0)
        window.warnings_panel.itemClicked.emit(item)
        cursor = window.editor.textCursor()
        assert (cursor.selectionStart(), cursor.selectionEnd()) == (7, 10)


class TestMetadataAndDirtyState:
    def test_author_and_date_update_document(self, qtbot, window) -> None:
        qtbot.keyClicks(window.author_edit, "Jan Kowalski")
        assert window.document.author == "Jan Kowalski"
        assert window.document.date
        assert window.document.is_dirty

    def test_dirty_mark_in_title(self, qtbot, window) -> None:
        assert not window.windowTitle().endswith("*")
        type_text(qtbot, window, "tekst")
        assert window.windowTitle().endswith("*")

    def test_mark_exported_clears_dirty_mark(self, qtbot, window) -> None:
        type_text(qtbot, window, "tekst")
        window.document.mark_exported()
        window._update_title()
        assert not window.windowTitle().endswith("*")


class TestKeyboardUndoRedo:
    def test_ctrl_z_undoes_typing(self, qtbot, window) -> None:
        type_text(qtbot, window, "pamientam")
        qtbot.keyClick(
            window.editor, Qt.Key.Key_Z, modifier=Qt.KeyboardModifier.ControlModifier
        )
        assert window.editor.toPlainText() != "pamientam"


class TestEllipsisStyle:
    """ACC-23..25: styl wielokropka, VAL-05 i „Ujednolić wielokropki”."""

    def test_acc23_unicode_cut_off_and_pause(self, qtbot, window) -> None:
        type_text(qtbot, window, "jeż… kam… kamionka rzeczy …bo")
        window.run_validation_now()
        texts = panel_texts(window)
        assert len(texts) == 1 and "VAL-01" in texts[0]

    def test_acc24_unify_is_one_undo_step(self, qtbot, window) -> None:
        window.editor.setPlainText("jeż... kam… rzeczy ... bo [...] […?]")
        window.unify_ellipses_action.trigger()
        assert window.editor.toPlainText() == "jeż… kam… rzeczy … bo [...] […?]"
        assert "2" in window.statusBar().currentMessage()
        window.editor.undo()
        assert window.editor.toPlainText() == "jeż... kam… rzeczy ... bo [...] […?]"

    def test_acc24_nothing_to_unify(self, window) -> None:
        window.editor.setPlainText("rzeczy … bo")
        window.unify_ellipses_action.trigger()
        assert window.editor.toPlainText() == "rzeczy … bo"
        assert "już" in window.statusBar().currentMessage()

    def test_acc25_style_change_keeps_text_and_hints(self, qtbot, window) -> None:
        window.editor.setPlainText("rzeczy … bo i jeż… tak")
        window.run_validation_now()
        assert window.warnings_panel.warning_count() == 0
        set_ellipsis_style(window, "ascii")
        window.run_validation_now()
        assert window.editor.toPlainText() == "rzeczy … bo i jeż… tak"
        assert [t.split(" ")[0] for t in panel_texts(window)] == ["VAL-05"] * 2

    def test_unify_locked_during_asr(self, window) -> None:
        window._set_ui_locked(True)
        assert not window.unify_ellipses_action.isEnabled()
        window._set_ui_locked(False)
        assert window.unify_ellipses_action.isEnabled()


def test_window_in_english_has_no_polish_toolbar_texts(add_window) -> None:
    """Język wczytany przy starcie obejmuje cały interfejs (pasek narzędzi)."""
    from transkryptor import i18n

    i18n.set_language(i18n.ENGLISH)
    window = add_window(MainWindow())
    texts = [action.text() for action in window.main_toolbar.toolbar.actions()]
    texts += [window.export_action.text(), window.save_action.text()]
    assert "Export DOCX…" in texts
    assert "Save project" in texts
    assert not any(set(text) & set("ąćęłńóśźż") for text in texts)
    assert window.player_bar.play_button.text() == "Play"
