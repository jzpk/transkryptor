"""Konfigurowalne skróty, wstawki i autouzupełnianie (ACC-43, ACC-44)."""

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QTextCharFormat
from PySide6.QtWidgets import QApplication, QMessageBox

from transkryptor.settings import (
    EditorSettings,
    Settings,
    ShortcutSettings,
    Snippet,
    SnippetSettings,
    encode_shortcut_map,
    encode_snippets,
    from_mapping,
    to_mapping,
)
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.shortcuts import (
    SHORTCUT_ACTIONS,
    effective_shortcuts,
    find_conflicts,
    marker_id,
    normalized,
    player_id,
    shortcut_overrides,
)
from transkryptor.ui.snippets import parse_snippet, snippet_label


def superscripts(window: MainWindow) -> list[str]:
    text = window.editor.plain_text()
    window.session.flush_editor()
    return [text[s:e] for s, e in window.document.superscript_ranges]


def show(qtbot, window: MainWindow) -> None:
    """Skróty działają tylko w widocznym, aktywnym oknie."""
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is window, timeout=3000)
    window.editor.setFocus()


def save_settings(window: MainWindow, **sections) -> None:
    store = window.settings_store
    store.save(replace(store.current, **sections))


class TestRegistry:
    def test_defaults_have_no_conflicts(self, qapp) -> None:
        mapping = effective_shortcuts({})
        assert find_conflicts(mapping) == []
        assert set(mapping) == {d.id for d in SHORTCUT_ACTIONS}

    def test_overrides_replace_defaults_and_empty_list_clears(self, qapp) -> None:
        mapping = effective_shortcuts(
            {marker_id("doubt"): ["ctrl+7"], player_id("play_pause"): []}
        )
        assert mapping[marker_id("doubt")] == ("Ctrl+7",)
        assert mapping[player_id("play_pause")] == ()
        assert mapping[marker_id("oddity")] == ("Ctrl+1",)

    def test_overrides_keep_only_changes(self, qapp) -> None:
        mapping = effective_shortcuts({})
        mapping[marker_id("doubt")] = ("Ctrl+7",)
        assert shortcut_overrides(mapping) == {marker_id("doubt"): ["Ctrl+7"]}

    def test_conflicts_between_actions_and_with_editing(self, qapp) -> None:
        mapping = effective_shortcuts({})
        mapping[marker_id("doubt")] = ("Ctrl+1",)  # zajęty przez „(!)”
        mapping[marker_id("aside")] = ("Ctrl+C",)  # kopiuj
        conflicts = find_conflicts(mapping)
        by_sequence = {c.sequence: c for c in conflicts}
        assert set(by_sequence) == {"Ctrl+1", "Ctrl+C"}
        assert set(by_sequence["Ctrl+1"].owners) == {
            marker_id("oddity"),
            marker_id("doubt"),
        }
        assert by_sequence["Ctrl+C"].standard == "copy"
        assert "kopiuj" in by_sequence["Ctrl+C"].message
        assert normalized("ctrl+c") == "Ctrl+C"

    def test_settings_round_trip(self) -> None:
        settings = Settings(
            editor=EditorSettings(autocomplete=True),
            shortcuts=ShortcutSettings(
                encode_shortcut_map({marker_id("doubt"): ["Ctrl+7"]})
            ),
            snippets=SnippetSettings(encode_snippets([Snippet("so^m", "Alt+1")])),
        )
        assert from_mapping(to_mapping(settings)) == settings
        broken = from_mapping({"snippets/spec": "[1]", "shortcuts/overrides_spec": "x"})
        assert broken.snippets == SnippetSettings()
        assert broken.shortcuts == ShortcutSettings()


class TestShortcutsInSettings:
    def test_acc43_conflict_is_reported_before_saving_then_free_key_works(
        self, qtbot, add_window, monkeypatch
    ) -> None:
        warnings: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda _p, _t, text, *a, **k: warnings.append(text)
        )
        window = add_window(MainWindow())
        dialog = window.create_settings_dialog()
        qtbot.addWidget(dialog)
        primary, _alt = dialog.shortcuts_editor.edits[marker_id("doubt")]
        primary.setKeySequence(QKeySequence("Ctrl+1"))  # zajęty przez „(!)”
        assert "Ctrl+1" in dialog.shortcuts_editor.conflicts_label.text()
        dialog.accept()
        assert dialog.result() != SettingsDialog.DialogCode.Accepted
        assert warnings and "Ctrl+1" in warnings[0]
        assert dialog.tabs.currentWidget() is dialog.shortcuts_editor

        primary.setKeySequence(QKeySequence("Ctrl+7"))
        assert dialog.shortcuts_editor.conflicts_label.text() == ""
        dialog.accept()
        assert dialog.result() == SettingsDialog.DialogCode.Accepted
        window.accept_settings_dialog(dialog)

        action = window.marker_actions["doubt"]
        assert [s.toString() for s in action.shortcuts()] == ["Ctrl+7"]
        assert "Ctrl+7" in action.toolTip() and "Ctrl+2" not in action.toolTip()
        show(qtbot, window)
        window.editor.clear()
        qtbot.keyClick(window.editor, Qt.Key.Key_7, Qt.KeyboardModifier.ControlModifier)
        assert window.editor.plain_text() == "(?)"

    def test_player_tooltips_follow_shortcuts(self, add_window) -> None:
        window = add_window(MainWindow())
        save_settings(
            window,
            shortcuts=ShortcutSettings(
                encode_shortcut_map({player_id("play_pause"): ["F9"]})
            ),
        )
        assert "F9" in window.player_bar.play_button.toolTip()
        assert "F4" not in window.player_bar.play_button.toolTip()
        assert [
            s.toString() for s in window.player_actions["play_pause"].shortcuts()
        ] == ["F9"]

    def test_restore_defaults_buttons(self, qtbot) -> None:
        dialog = SettingsDialog(
            Settings(
                shortcuts=ShortcutSettings(
                    encode_shortcut_map({marker_id("doubt"): ["Ctrl+7"]})
                )
            )
        )
        qtbot.addWidget(dialog)
        editor = dialog.shortcuts_editor
        assert editor.mapping()[marker_id("doubt")] == ("Ctrl+7",)
        row = [d.id for d in SHORTCUT_ACTIONS].index(marker_id("doubt"))
        editor.table.setCurrentCell(row, 0)
        editor.reset_current_row()
        assert editor.mapping()[marker_id("doubt")] == ("Ctrl+2",)
        assert dialog.settings().shortcuts == ShortcutSettings()


class TestSnippets:
    def test_acc44_snippet_under_alt1_inserts_superscript_in_one_undo_step(
        self, qtbot, add_window
    ) -> None:
        window = add_window(MainWindow())
        dialog = window.create_settings_dialog()
        qtbot.addWidget(dialog)
        row = dialog.snippets_editor.add_snippet()
        dialog.snippets_editor.set_text(row, "so^m")
        assert dialog.snippets_editor.snippets() == (Snippet("so^m", "Alt+1"),)
        dialog.accept()
        window.accept_settings_dialog(dialog)

        window.editor.setPlainText("to ")
        cursor = window.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        show(qtbot, window)
        qtbot.keyClick(window.editor, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
        assert window.editor.plain_text() == "to som"
        assert superscripts(window) == ["m"]
        window.editor.undo()
        assert window.editor.plain_text() == "to "

    def test_snippet_does_not_inherit_superscript(self, add_window) -> None:
        window = add_window(MainWindow())
        window.editor.setPlainText("m")
        cursor = window.editor.textCursor()
        cursor.select(cursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        cursor.movePosition(cursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        parsed = parse_snippet("ab")
        assert parsed is not None
        window.snippets.insert(parsed)
        assert superscripts(window) == ["m"]

    def test_menu_lists_snippets_and_conflicts_with_actions(
        self, qtbot, add_window
    ) -> None:
        window = add_window(MainWindow())
        save_settings(
            window,
            snippets=SnippetSettings(encode_snippets([Snippet("so^m", "Alt+1")])),
        )
        texts = [a.text() for a in window.main_toolbar.snippets_menu.actions()]
        assert "soᵐ" in texts
        dialog = window.create_settings_dialog()
        qtbot.addWidget(dialog)
        row = dialog.snippets_editor.add_snippet("uo^n", "Ctrl+1")
        assert row == 1
        assert any("Ctrl+1" in m for m in dialog.shortcut_conflicts())

    def test_snippets_are_locked_during_transcription(self, add_window) -> None:
        window = add_window(MainWindow())
        save_settings(
            window,
            snippets=SnippetSettings(encode_snippets([Snippet("so^m", "Alt+1")])),
        )
        window._set_ui_locked(True)
        assert not any(a.isEnabled() for a in window.snippets.actions)
        window._set_ui_locked(False)
        assert all(a.isEnabled() for a in window.snippets.actions)

    def test_invalid_snippet_blocks_accept(self, qtbot, monkeypatch) -> None:
        monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: None)
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        row = dialog.snippets_editor.add_snippet()
        dialog.snippets_editor.set_text(row, "so^")
        assert dialog.snippets_editor.problem_label.text()
        dialog.accept()
        assert dialog.result() != SettingsDialog.DialogCode.Accepted

    def test_snippet_label_shows_modifier_letters(self) -> None:
        parsed = parse_snippet("^uo^n")
        assert parsed is not None and snippet_label(parsed) == "ᵘoⁿ"


class TestAutocomplete:
    def _window(self, add_window) -> MainWindow:
        window = add_window(MainWindow())
        save_settings(
            window,
            editor=EditorSettings(autocomplete=True),
            snippets=SnippetSettings(encode_snippets([Snippet("so^m")])),
        )
        return window

    def test_disabled_by_default(self, add_window) -> None:
        window = add_window(MainWindow())
        window.editor.setPlainText("pamientam pa")
        cursor = window.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        assert not window.snippets.complete_now()

    def test_document_words_are_suggested_and_inserted(self, add_window) -> None:
        window = self._window(add_window)
        window.editor.setPlainText("pamientam dobrze, pa")
        window.snippets.refresh_completions()
        cursor = window.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        assert window.snippets.current_prefix() == "pa"
        assert window.snippets.complete_now()
        assert window.snippets.completer.currentCompletion() == "pamientam"
        window.snippets.insert_completion("pamientam")
        assert window.editor.plain_text() == "pamientam dobrze, pamientam"
        window.editor.undo()
        assert window.editor.plain_text() == "pamientam dobrze, pa"

    def test_snippet_completion_keeps_superscript(self, add_window) -> None:
        window = self._window(add_window)
        window.editor.setPlainText("so")
        cursor = window.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        window.editor.setTextCursor(cursor)
        assert window.snippets.complete_now()
        window.snippets.insert_completion("som")
        assert window.editor.plain_text() == "som"
        assert superscripts(window) == ["m"]
