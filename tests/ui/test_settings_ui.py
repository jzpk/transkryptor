"""Testy ustawień w UI: trwałość, okno ustawień i stosowanie bez restartu."""

from PySide6.QtWidgets import QDialog, QWidget

from transkryptor.settings import (
    AppearanceSettings,
    EditorSettings,
    NotationSettings,
    PlayerSettings,
    Settings,
)
from transkryptor.ui.editor import EDITOR_FONT_SCALE
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.settings_store import SettingsStore

CUSTOM = Settings(
    player=PlayerSettings(
        skip_ms=5000,
        auto_rewind_enabled=False,
        auto_rewind_ms=2500,
        segment_preroll_ms=1000,
    ),
    editor=EditorSettings(font_family="", font_size_pt=20),
    notation=NotationSettings(ellipsis_style="ascii"),
    appearance=AppearanceSettings(theme="dark"),
)


class TestSettingsStore:
    def test_missing_file_gives_defaults(self, isolated_settings) -> None:
        store = SettingsStore(isolated_settings())
        assert store.load() == Settings()

    def test_save_persists_and_emits(self, qtbot, isolated_settings) -> None:
        store = SettingsStore(isolated_settings())
        with qtbot.waitSignal(store.settings_changed) as blocker:
            store.save(CUSTOM)
        assert blocker.args == [CUSTOM]
        assert store.current == CUSTOM
        assert SettingsStore(isolated_settings()).load() == CUSTOM

    def test_corrupted_values_fall_back_to_defaults(self, isolated_settings) -> None:
        """ACC-18: błędne pola → domyślne, bez błędu blokującego."""
        raw = isolated_settings()
        raw.setValue("player/skip_ms", "nie-liczba")
        raw.setValue("player/auto_rewind_ms", 2000)
        raw.setValue("editor/font_size_pt", 500)
        raw.setValue("obce/pole", "x")
        raw.sync()
        settings = SettingsStore(isolated_settings()).load()
        assert settings.player.skip_ms == PlayerSettings().skip_ms
        assert settings.player.auto_rewind_ms == 2000
        assert settings.editor.font_size_pt == 0

    def test_garbage_file_does_not_block(self, tmp_path, isolated_settings) -> None:
        (tmp_path / "settings.ini").write_bytes(b"\x00\xff[[[ to nie jest INI")
        assert SettingsStore(isolated_settings()).load() == Settings()


class TestSettingsDialog:
    def test_round_trip_through_fields(self, qtbot) -> None:
        dialog = SettingsDialog(CUSTOM)
        qtbot.addWidget(dialog)
        assert dialog.settings() == CUSTOM
        assert not dialog.auto_rewind_spin.isEnabled()

    def test_defaults_round_trip(self, qtbot) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        assert dialog.settings() == Settings()
        assert dialog.font_size_spin.text() == "Domyślny"

    def test_restore_defaults(self, qtbot) -> None:
        dialog = SettingsDialog(CUSTOM)
        qtbot.addWidget(dialog)
        dialog.restore_defaults_button.click()
        assert dialog.settings() == Settings()

    def test_custom_font_family(self, qtbot) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        dialog.default_font_check.setChecked(False)
        family = dialog.font_combo.currentFont().family()
        assert dialog.settings().editor.font_family == family

    def test_ellipsis_style_hint_shown_only_after_change(self, qtbot) -> None:
        """Okno ustawień podpowiada „Ujednolić wielokropki” po zmianie stylu."""
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        # Podpowiedź leży na zakładce „Notacja”, niekoniecznie bieżącej.
        assert dialog.ellipsis_hint.isHidden()
        dialog.ellipsis_combo.setCurrentIndex(dialog.ellipsis_combo.findData("ascii"))
        assert not dialog.ellipsis_hint.isHidden()
        assert "Ujednolić" in dialog.ellipsis_hint.text()
        assert dialog.settings().notation.ellipsis_style == "ascii"

    def test_tabs_group_settings_by_area(self, qtbot) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        assert titles == ["Wygląd", "Odtwarzacz", "Notacja", "Projekt", "Metryczka"]

        def tab_of(widget: QWidget) -> str:
            for index in range(dialog.tabs.count()):
                page = dialog.tabs.widget(index)
                if page is not None and page.isAncestorOf(widget):
                    return dialog.tabs.tabText(index)
            return ""

        assert tab_of(dialog.theme_combo) == "Wygląd"
        assert tab_of(dialog.font_size_spin) == "Wygląd"
        assert tab_of(dialog.skip_spin) == "Odtwarzacz"
        assert tab_of(dialog.ellipsis_combo) == "Notacja"
        assert tab_of(dialog.autosave_check) == "Projekt"
        assert tab_of(dialog.metadata_table) == "Metryczka"

    def test_theme_choice(self, qtbot) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        assert dialog.settings().appearance.theme == "system"
        dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("light"))
        assert dialog.settings().appearance.theme == "light"


class TestMainWindowSettings:
    def test_settings_action_shortcut(self, add_window) -> None:
        window = add_window(MainWindow())
        assert window.settings_action.shortcut().toString() == "Ctrl+,"

    def test_changes_apply_without_restart_and_persist(
        self, add_window, monkeypatch, isolated_settings
    ) -> None:
        """ACC-17: zmiana działa od razu i przetrwa ponowne uruchomienie."""
        window = add_window(MainWindow())
        default_size = window.editor.font().pointSizeF()

        def accept(dialog):
            dialog.font_size_spin.setValue(22)
            dialog.auto_rewind_spin.setValue(3.0)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(SettingsDialog, "exec", accept)
        window.settings_action.trigger()

        assert window.editor.font().pointSizeF() == 22
        assert window.player_bar._settings.auto_rewind_ms == 3000
        assert default_size != 22

        restarted = add_window(MainWindow())
        assert restarted.editor.font().pointSizeF() == 22
        assert restarted.settings_store.current.player.auto_rewind_ms == 3000

    def test_cancel_changes_nothing(self, add_window, monkeypatch) -> None:
        window = add_window(MainWindow())

        def cancel(dialog):
            dialog.font_size_spin.setValue(30)
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(SettingsDialog, "exec", cancel)
        window.settings_action.trigger()
        assert window.settings_store.current == Settings()
        assert window.editor.font().pointSizeF() != 30

    def test_default_font_size_is_scaled(self, qtbot) -> None:
        from transkryptor.ui.editor import TranscriptionEditor

        editor = TranscriptionEditor()
        qtbot.addWidget(editor)
        base = editor._base_font.pointSizeF()
        assert editor.font().pointSizeF() == base * EDITOR_FONT_SCALE
        editor.apply_settings(EditorSettings(font_size_pt=18))
        editor.apply_settings(EditorSettings())
        assert editor.font().pointSizeF() == base * EDITOR_FONT_SCALE

    def test_font_change_keeps_text_and_undo(self, add_window) -> None:
        window = add_window(MainWindow())
        window.editor.setPlainText("abc")
        undo_steps = window.editor.document().availableUndoSteps()
        window.settings_store.save(CUSTOM)
        assert window.editor.toPlainText() == "abc"
        assert window.editor.document().availableUndoSteps() == undo_steps

    def test_theme_switches_without_restart(self, add_window, qapp) -> None:
        from transkryptor.ui import icons, theme

        window = add_window(MainWindow())
        previous_style = qapp.styleSheet()
        try:
            window.settings_store.save(
                Settings(appearance=AppearanceSettings(theme="dark"))
            )
            assert theme.tokens() is theme.DARK
            assert theme.DARK.surface in qapp.styleSheet()
            # Ikony przerysowane w kolorach nowego motywu.
            expected = icons.themed("save", "text", "text_muted").cacheKey()
            assert window.save_action.icon().cacheKey() == expected
            window.settings_store.save(
                Settings(appearance=AppearanceSettings(theme="light"))
            )
            assert theme.tokens() is theme.LIGHT
        finally:
            theme.apply_theme(qapp, theme.LIGHT)
            qapp.setStyleSheet(previous_style)

    def test_settings_locked_during_asr(self, add_window) -> None:
        window = add_window(MainWindow())
        window._set_ui_locked(True)
        assert not window.settings_action.isEnabled()
        window._set_ui_locked(False)
        assert window.settings_action.isEnabled()
