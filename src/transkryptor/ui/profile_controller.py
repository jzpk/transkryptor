"""Profile notacji w oknie: aktywny profil, przełącznik i profil projektu.

Bieżące ustawienia i reguły użytkownika są roboczą kopią aktywnego profilu
(``transkryptor.profiles``): każda ich zmiana trafia do pliku profilu,
a przełączenie profilu wpisuje jego wartości do ustawień i pliku reguł.
Przy pierwszym uruchomieniu wersji z profilami obecne ustawienia stają się
profilem „Domyślny” - bez utraty danych.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QSizePolicy, QWidget

from transkryptor import paths
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.rules import builtin_codes, dumps_rules, parse_rules
from transkryptor.profiles import (
    NotationProfile,
    ProfileLibrary,
    apply_profile,
    capture,
    read_profile,
    unique_name,
    write_profile,
)
from transkryptor.settings import Settings
from transkryptor.ui.messages import show_error
from transkryptor.ui.rules_store import RulesStore
from transkryptor.ui.settings_store import SettingsStore

logger = logging.getLogger(__name__)


class ProfileController(QObject):
    """Biblioteka profili, aktywny profil i szybki przełącznik w pasku stanu."""

    # Lista profili albo aktywny profil zmieniły się.
    profiles_changed = Signal()

    def __init__(
        self,
        window: QWidget,
        settings_store: SettingsStore,
        rules_store: RulesStore,
        show_status: Callable[[str], None],
        library: ProfileLibrary | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._settings_store = settings_store
        self._rules_store = rules_store
        self._show_status = show_status
        self.library = library or ProfileLibrary(paths.profiles_dir())
        self._switching = False
        self._saved: NotationProfile | None = None
        self.switcher = self._build_switcher()
        self.ensure_active()
        settings_store.settings_changed.connect(lambda _settings: self.sync())
        rules_store.rules_changed.connect(self.sync)
        self.profiles_changed.connect(self._refresh_switcher)
        self._refresh_switcher()

    def _build_switcher(self) -> QComboBox:
        switcher = QComboBox()
        switcher.setObjectName("profile_switcher")
        switcher.setToolTip(tr("profiles.switcher.tooltip"))
        switcher.setAccessibleName(tr("profiles.switcher"))
        switcher.setAccessibleDescription(tr("profiles.switcher.tooltip"))
        switcher.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        switcher.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        switcher.activated.connect(
            lambda index: self.switch_to(str(switcher.itemData(index)))
        )
        return switcher

    def _refresh_switcher(self) -> None:
        self.switcher.blockSignals(True)
        self.switcher.clear()
        for name in self.names():
            self.switcher.addItem(tr("profiles.switcher.item", name=name), name)
        self.switcher.setCurrentIndex(max(self.switcher.findData(self.active), 0))
        self.switcher.blockSignals(False)

    # --- stan ------------------------------------------------------------

    @property
    def active(self) -> str:
        return self._settings_store.current.profiles.active

    def names(self) -> list[str]:
        return self.library.names()

    def current_profile(self, name: str | None = None) -> NotationProfile:
        """Profil z bieżących ustawień i reguł (pod nazwą aktywnego profilu)."""
        rules = self._rules_store.user_rules
        return capture(
            self.active if name is None else name,
            self._settings_store.current,
            dumps_rules(rules) if rules else "",
        )

    def ensure_active(self) -> None:
        """Aktywny profil istnieje; inaczej powstaje z bieżących ustawień.

        Przy pierwszym uruchomieniu (pusta biblioteka) to migracja obecnych
        ustawień do profilu „Domyślny”.
        """
        names = self.names()
        if self.active and self.active in names:
            self._saved = self.library.load(self.active)
            return
        name = unique_name(self.active or tr("profiles.default_name"), names)
        logger.info("Creating notation profile from current settings")
        current = self._settings_store.current
        self._switching = True
        try:
            self._settings_store.save(
                replace(current, profiles=replace(current.profiles, active=name))
            )
        finally:
            self._switching = False
        self.sync()

    def sync(self) -> None:
        """Zapisuje roboczą kopię do pliku aktywnego profilu (gdy się zmieniła)."""
        if self._switching or not self.active:
            return
        profile = self.current_profile()
        if profile == self._saved:
            return
        try:
            self.library.save(profile)
        except AppError as error:
            logger.warning("Notation profile could not be saved: %s", error)
            self._show_status(tr("profiles.status.save_error", name=profile.name))
            return
        self._saved = profile

    def set_locked(self, locked: bool) -> None:
        """Bez zmiany profilu w trakcie ASR (reguły szkicu są w użyciu)."""
        self.switcher.setEnabled(not locked)

    # --- przełączanie ----------------------------------------------------

    def switch_to(self, name: str) -> bool:
        """Wpisuje profil ``name`` do ustawień i reguł; False przy błędzie."""
        if name == self.active:
            return True
        self.sync()
        profile = self.library.load(name)
        if profile is None:
            self._show_status(tr("profiles.status.missing", name=name))
            self._refresh_switcher()
            return False
        rules = parse_rules(
            profile.rules_toml, "rules.toml", taken_codes=builtin_codes()
        ).rules
        self._switching = True
        try:
            if rules != self._rules_store.user_rules:
                self._rules_store.save_user_rules(rules)
            self._settings_store.save(
                apply_profile(profile, self._settings_store.current)
            )
        except AppError as error:
            show_error(self._window, tr("profiles.error.switch"), error)
            return False
        finally:
            self._switching = False
        self._saved = profile
        self.profiles_changed.emit()
        self._show_status(tr("profiles.status.switched", name=name))
        return True

    def save_settings(self, settings: Settings) -> None:
        """Ustawienia z okna „Ustawienia…”: zmiany pól należą do bieżącego
        profilu, a wybrany na zakładce „Profile” profil staje się aktywny."""
        target = settings.profiles.active
        current = self._settings_store.current
        self._settings_store.save(replace(settings, profiles=current.profiles))
        if target != self.active and target in self.names():
            self.switch_to(target)

    def use_project_profile(self, name: str) -> None:
        """Projekt otwarty z zapamiętanym profilem - przełącza na niego."""
        if not name or name == self.active:
            return
        if name not in self.names():
            self._show_status(
                tr("profiles.status.project_missing", name=name, active=self.active)
            )
            return
        if self.switch_to(name):
            self._show_status(tr("profiles.status.project", name=name))

    # --- operacje na bibliotece (zakładka „Profile”) ---------------------

    def create(self, name: str, copy_current: bool) -> str:
        """Nowy profil (kopia bieżącego albo pusty); zwraca nadaną nazwę."""
        self.sync()
        unique = unique_name(name, self.names())
        profile = (
            self.current_profile(unique) if copy_current else NotationProfile(unique)
        )
        self.library.save(profile)
        self.profiles_changed.emit()
        return unique

    def rename(self, old: str, new: str) -> str | None:
        """Zmienia nazwę profilu (także aktywnego); zwraca nową nazwę."""
        unique = unique_name(new, [n for n in self.names() if n != old])
        if unique == old:
            return old
        self.sync()
        renamed = self.library.rename(old, unique)
        if renamed is None:
            return None
        if old == self.active:
            current = self._settings_store.current
            self._switching = True
            try:
                self._settings_store.save(
                    replace(current, profiles=replace(current.profiles, active=unique))
                )
            finally:
                self._switching = False
            self._saved = renamed
        self.profiles_changed.emit()
        return unique

    def delete(self, name: str) -> bool:
        """Usuwa profil; aktywnego profilu nie można usunąć."""
        if name == self.active:
            return False
        self.library.delete(name)
        self.profiles_changed.emit()
        return True

    def import_file(self, path: Path) -> str:
        """Dodaje profil z pliku (``ProfileError`` przy błędnym pliku)."""
        profile = read_profile(path)
        name = unique_name(profile.name, self.names())
        self.library.save(profile.renamed(name))
        self.profiles_changed.emit()
        return name

    def export_file(self, name: str, path: Path) -> None:
        """Zapisuje profil do pliku dla zespołu."""
        self.sync()
        profile = self.library.load(name)
        if profile is None:
            return
        write_profile(profile, path)
