"""Trwałość ustawień użytkownika przez ``QSettings``.

Model i walidacja są w ``transkryptor.settings`` (bez Qt); ten moduł tylko
czyta i zapisuje płaski słownik. Linux: ``~/.config/transkryptor/
transkryptor.conf``, Windows: rejestr ``HKCU\\Software\\transkryptor``.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

from transkryptor.settings import Settings, from_mapping, to_mapping

SETTINGS_ORGANIZATION = "transkryptor"
SETTINGS_APPLICATION = "transkryptor"


def default_qsettings() -> QSettings:
    """Magazyn ustawień użytkownika (podmieniany w testach na plik INI)."""
    return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


class SettingsStore(QObject):
    """Bieżące ustawienia z odczytem przy starcie i zapisem po zatwierdzeniu."""

    settings_changed = Signal(object)  # Settings

    def __init__(
        self, qsettings: QSettings | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._qsettings = qsettings if qsettings is not None else default_qsettings()
        self._current = Settings()

    @property
    def current(self) -> Settings:
        return self._current

    def load(self) -> Settings:
        """Wczytuje ustawienia; błędne pola dostają wartości domyślne (ACC-18)."""
        try:
            mapping = {
                key: self._qsettings.value(key) for key in self._qsettings.allKeys()
            }
        except Exception:  # noqa: BLE001 — uszkodzony magazyn nie blokuje startu
            mapping = {}
        self._current = from_mapping(mapping)
        return self._current

    def save(self, settings: Settings) -> None:
        """Zapisuje ustawienia i powiadamia komponenty (bez restartu)."""
        for key, value in to_mapping(settings).items():
            self._qsettings.setValue(key, value)
        self._qsettings.sync()
        self._current = settings
        self.settings_changed.emit(settings)
