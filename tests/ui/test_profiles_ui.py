"""Profile notacji w oknie: migracja, przełączanie, projekt i zakładka „Profile”."""

import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from transkryptor.notation.rules import PhoneticRule
from transkryptor.profiles import NotationProfile, ProfileLibrary, dumps_profile
from transkryptor.settings import (
    EditorSettings,
    NotationSettings,
    ProfileSettings,
    Settings,
    ValidatorSettings,
)
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.settings_store import SettingsStore

RULE = PhoneticRule("USR-UO", {"*": "uo"}, "o", "uo", 0.5)


@pytest.fixture
def window(add_window) -> MainWindow:
    return add_window(MainWindow())


def library(isolated_profiles) -> ProfileLibrary:
    return ProfileLibrary(isolated_profiles)


class TestMigration:
    def test_first_start_creates_default_profile_from_settings(
        self, add_window, isolated_settings, isolated_profiles
    ) -> None:
        store = SettingsStore(isolated_settings())
        store.save(
            Settings(
                notation=NotationSettings(ellipsis_style="ascii"),
                validator=ValidatorSettings(overrides_spec='{"NOT-1": false}'),
            )
        )
        window = add_window(MainWindow(settings_store=store))
        assert window.profiles.active == "Domyślny"
        assert library(isolated_profiles).names() == ["Domyślny"]
        profile = library(isolated_profiles).load("Domyślny")
        assert profile is not None
        assert profile.ellipsis_style == "ascii"
        assert profile.validator_spec == '{"NOT-1": false}'
        # Ustawienia zostają bez zmian (bez utraty danych).
        assert store.current.notation.ellipsis_style == "ascii"
        assert SettingsStore(isolated_settings()).load().profiles.active == "Domyślny"

    def test_default_profile_keeps_user_rules(
        self, add_window, isolated_profiles
    ) -> None:
        from transkryptor.ui.rules_store import RulesStore

        RulesStore().save_user_rules([RULE])
        add_window(MainWindow())
        profile = library(isolated_profiles).load("Domyślny")
        assert profile is not None
        assert "USR-UO" in profile.rules_toml

    def test_existing_profile_is_reused(self, add_window, isolated_profiles) -> None:
        library(isolated_profiles).save(NotationProfile("Zespół", autocomplete=True))
        store = SettingsStore()
        store.load()
        store.save(replace(store.current, profiles=ProfileSettings(active="Zespół")))
        window = add_window(MainWindow(settings_store=store))
        assert window.profiles.names() == ["Zespół"]
        assert window.profiles.active == "Zespół"


class TestSwitching:
    def test_changes_are_saved_to_the_active_profile(
        self, window, isolated_profiles
    ) -> None:
        current = window.settings_store.current
        window.settings_store.save(
            replace(current, editor=replace(current.editor, autocomplete=True))
        )
        window.rules_store.save_user_rules([RULE])
        profile = library(isolated_profiles).load("Domyślny")
        assert profile is not None
        assert profile.autocomplete
        assert "USR-UO" in profile.rules_toml

    def test_switch_replaces_settings_and_rules(
        self, window, isolated_profiles
    ) -> None:
        window.rules_store.save_user_rules([RULE])
        library(isolated_profiles).save(
            NotationProfile("Gwara", ellipsis_style="ascii", autocomplete=True)
        )
        window.profiles.profiles_changed.emit()
        assert window.profiles.switch_to("Gwara")
        settings = window.settings_store.current
        assert settings.profiles.active == "Gwara"
        assert settings.notation.ellipsis_style == "ascii"
        assert settings.editor.autocomplete
        assert window.rules_store.user_rules == ()
        # Poprzedni profil zachował swoje reguły - powrót je przywraca.
        assert window.profiles.switch_to("Domyślny")
        assert [rule.code for rule in window.rules_store.user_rules] == ["USR-UO"]
        assert not window.settings_store.current.editor.autocomplete

    def test_switcher_in_status_bar(self, window, isolated_profiles) -> None:
        library(isolated_profiles).save(NotationProfile("Gwara"))
        window.profiles.profiles_changed.emit()
        switcher = window.profiles.switcher
        assert switcher.objectName() == "profile_switcher"
        assert switcher.accessibleName() == "Profil notacji"
        assert [switcher.itemData(i) for i in range(switcher.count())] == [
            "Domyślny",
            "Gwara",
        ]
        switcher.setCurrentIndex(1)
        switcher.activated.emit(1)
        assert window.profiles.active == "Gwara"
        assert "Gwara" in window.statusBar().currentMessage()

    def test_switcher_is_locked_during_asr(self, window) -> None:
        window._set_ui_locked(True)
        assert not window.profiles.switcher.isEnabled()
        window._set_ui_locked(False)
        assert window.profiles.switcher.isEnabled()


class TestProjectProfile:
    def test_project_opens_with_its_profile(
        self, window, add_window, isolated_profiles, tmp_path
    ) -> None:
        library(isolated_profiles).save(
            NotationProfile("Gwara", ellipsis_style="ascii")
        )
        window.profiles.profiles_changed.emit()
        assert window.profiles.switch_to("Gwara")
        window.editor.setPlainText("tekst projektu")
        path = tmp_path / "wywiad.transkr"
        window.session.project_path = path
        assert window.session.save_project()
        assert json.loads(path.read_text(encoding="utf-8"))["profile"] == "Gwara"

        assert window.profiles.switch_to("Domyślny")
        assert window.session.open_project(path, confirm=False)
        assert window.profiles.active == "Gwara"
        assert window.settings_store.current.notation.ellipsis_style == "ascii"
        assert "Gwara" in window.statusBar().currentMessage()

    def test_missing_profile_keeps_current(self, window, tmp_path) -> None:
        window.editor.setPlainText("tekst")
        path = tmp_path / "wywiad.transkr"
        window.session.project_path = path
        assert window.session.save_project()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["profile"] = "Nieznany"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert window.session.open_project(path, confirm=False)
        assert window.profiles.active == "Domyślny"
        assert "Nieznany" in window.statusBar().currentMessage()


class TestProfilesPage:
    def dialog(self, window) -> SettingsDialog:
        return window.create_settings_dialog()

    def test_tab_lists_profiles_and_marks_current(self, window) -> None:
        dialog = self.dialog(window)
        page = dialog.profiles_page
        assert dialog.tabs.tabText(dialog.tabs.indexOf(page)) == "Profile"
        assert page.names() == ["Domyślny"]
        assert page.profiles_list.item(0).text() == "Domyślny (bieżący)"
        assert not page.delete_button.isEnabled()

    def test_new_copy_rename_delete(self, window, isolated_profiles) -> None:
        current = window.settings_store.current
        window.settings_store.save(
            replace(current, editor=replace(current.editor, autocomplete=True))
        )
        page = self.dialog(window).profiles_page
        assert page.create_profile("Kopia", copy_current=True) == "Kopia"
        assert page.create_profile("Pusty", copy_current=False) == "Pusty"
        assert page.create_profile("Pusty", copy_current=False) == "Pusty (2)"
        lib = library(isolated_profiles)
        copy = lib.load("Kopia")
        empty = lib.load("Pusty")
        assert copy is not None and copy.autocomplete
        assert empty == NotationProfile("Pusty")
        assert page.rename_profile("Pusty (2)", "Trzeci") == "Trzeci"
        assert page.delete_profile("Trzeci")
        assert not page.delete_profile("Domyślny")
        assert page.names() == ["Domyślny", "Kopia", "Pusty"]

    def test_rename_current_profile(self, window, isolated_profiles) -> None:
        page = self.dialog(window).profiles_page
        assert page.rename_profile("Domyślny", "Mój standard") == "Mój standard"
        assert window.profiles.active == "Mój standard"
        assert library(isolated_profiles).names() == ["Mój standard"]
        assert page.profiles_list.item(0).text() == "Mój standard (bieżący)"

    def test_buttons_use_dialogs(self, window, monkeypatch, isolated_profiles) -> None:
        page = self.dialog(window).profiles_page
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Nowy", True))
        )
        page.new_button.click()
        assert "Nowy" in page.names()
        page.select("Nowy")
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        page.delete_button.click()
        assert "Nowy" not in page.names()

    def test_export_and_import(self, window, tmp_path, isolated_profiles) -> None:
        current = window.settings_store.current
        window.settings_store.save(
            replace(current, editor=replace(current.editor, autocomplete=True))
        )
        page = self.dialog(window).profiles_page
        exported = tmp_path / "zespol.json"
        assert page.export_profile("Domyślny", exported)
        assert json.loads(exported.read_text(encoding="utf-8"))["autocomplete"]
        assert page.import_profile(exported) == "Domyślny (2)"
        imported = library(isolated_profiles).load("Domyślny (2)")
        assert imported is not None and imported.autocomplete

    def test_broken_import_shows_error(
        self, window, tmp_path, no_blocking_dialogs
    ) -> None:
        broken = tmp_path / "zly.json"
        broken.write_text("{", encoding="utf-8")
        page = self.dialog(window).profiles_page
        assert page.import_profile(broken) is None
        assert any("zly.json" in text for _kind, _title, text in no_blocking_dialogs)

    def test_ok_switches_to_selected_profile_after_saving_edits(
        self, window, isolated_profiles
    ) -> None:
        library(isolated_profiles).save(
            NotationProfile("Gwara", ellipsis_style="ascii")
        )
        dialog = self.dialog(window)
        dialog.profiles_page.load(window.settings_store.current)
        dialog.notation_page.autocomplete_check.setChecked(True)
        dialog.profiles_page.select("Gwara")
        window.accept_settings_dialog(dialog)
        assert window.profiles.active == "Gwara"
        assert window.settings_store.current.notation.ellipsis_style == "ascii"
        # Zmiana z innej zakładki trafiła do poprzedniego profilu.
        default = library(isolated_profiles).load("Domyślny")
        assert default is not None and default.autocomplete

    def test_dialog_without_library(self, qtbot) -> None:
        dialog = SettingsDialog(Settings(editor=EditorSettings()))
        qtbot.addWidget(dialog)
        assert dialog.profiles_page.names() == []
        assert not dialog.profiles_page.new_button.isEnabled()
        assert dialog.settings() == Settings()


def test_profile_file_is_shared_format(isolated_profiles) -> None:
    """Plik w bibliotece ma ten sam format co eksport (da się go przekazać)."""
    lib = library(isolated_profiles)
    lib.save(NotationProfile("A"))
    (path,) = isolated_profiles.glob("*.json")
    assert path.read_text(encoding="utf-8") == dumps_profile(NotationProfile("A"))
