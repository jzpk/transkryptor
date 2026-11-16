"""Wspólny folder zapisu projektów, eksportów i paczek.

Bez niego okna zapisu startowały w różnych miejscach: projekt obok
nagrania, eksport w katalogu bieżącym procesu (zwykle katalogu programu),
a wybrany ręcznie folder nie był zapamiętywany. Teraz:

- folder wybrany przez użytkownika (w ustawieniach albo w oknie zapisu)
  jest nadrzędny: wszystkie okna zapisu startują w nim, także dla projektu
  otwartego z innego miejsca;
- dopóki użytkownik nie wybrał folderu, eksport i paczka zapisanego
  projektu startują obok niego, a bez pliku projektu - w folderze
  domyślnym ``Dokumenty/Transkryptor`` (tworzonym przy pierwszym zapisie).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QWidget

from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.settings_store import SettingsStore

logger = logging.getLogger(__name__)

DEFAULT_FOLDER_NAME = "Transkryptor"


def default_save_dir() -> Path:
    """Folder ``Transkryptor`` w Dokumentach (bez nich - w katalogu domowym).

    Testy podmieniają tę funkcję w ``tests/conftest.py`` - nie mogą tworzyć
    folderów w Dokumentach dewelopera.
    """
    documents = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation
    )
    base = Path(documents) if documents else Path.home()
    return base / DEFAULT_FOLDER_NAME


class SaveLocation:
    """Folder, w którym startują okna zapisu i otwierania plików pracy."""

    def __init__(
        self,
        settings_store: SettingsStore,
        project_path: Callable[[], Path | None] = lambda: None,
    ) -> None:
        self._settings_store = settings_store
        self._project_path = project_path

    def chosen(self) -> Path | None:
        """Folder wybrany przez użytkownika; None - brak wyboru albo usunięty."""
        chosen = self._settings_store.current.project.save_dir.strip()
        if chosen and Path(chosen).is_dir():
            return Path(chosen)
        return None

    def start_dir(self) -> str:
        """Folder startowy okna: wybrany, obok zapisanego projektu albo domyślny.

        Folder domyślny powstaje tu, żeby okno mogło się w nim otworzyć; gdy
        się nie da (brak uprawnień), okno startuje w katalogu domowym.
        """
        chosen = self.chosen()
        if chosen is not None:
            return str(chosen)
        project = self._project_path()
        if project is not None and project.parent.is_dir():
            return str(project.parent)
        folder = default_save_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Save folder could not be created", exc_info=True)
            return str(Path.home())
        return str(folder)

    def ask(
        self,
        parent: QWidget,
        title: str,
        name: str,
        file_filter: str,
        suffix: str,
    ) -> Path | None:
        """Okno zapisu pliku ``name`` w folderze startowym; zapamiętuje wybór."""
        default = str(Path(self.start_dir()) / Path(name).name)
        path = ask_save_path(parent, title, default, file_filter, suffix)
        if path is not None:
            self.remember(path)
        return path

    def remember(self, path: Path) -> None:
        """Folder pliku ``path`` staje się folderem zapisu.

        Zapis w folderze domyślnym czyści wybór - pole w ustawieniach zostaje
        puste, a folder domyślny i dalej projekt wyznaczają miejsce.
        """
        folder = "" if path.parent == default_save_dir() else str(path.parent)
        current = self._settings_store.current
        if current.project.save_dir == folder:
            return
        self._settings_store.save(
            replace(current, project=replace(current.project, save_dir=folder))
        )
