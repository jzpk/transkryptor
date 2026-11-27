"""Nagranie projektu przy otwieraniu: wyszukanie, wskazanie ręczne, suma SHA-256."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from transkryptor.audio.formats import file_dialog_filter as audio_filter
from transkryptor.document.project import ProjectState, resolve_audio
from transkryptor.i18n import tr


class AudioLocator:
    """Znajduje nagranie projektu i pyta użytkownika, gdy go brak albo się zmieniło.

    ``hash_now`` liczy sumę wskazanego pliku od razu (z oknem postępu).
    """

    def __init__(self, parent: QWidget, hash_now: Callable[[Path], str | None]) -> None:
        self._parent = parent
        self._hash_now = hash_now

    def locate(
        self, state: ProjectState, project_path: Path | None
    ) -> tuple[Path | None, str | None]:
        """Nagranie projektu: ścieżka względna, bezwzględna albo wskazane ręcznie.

        Przy innej sumie SHA-256 użytkownik decyduje, czy użyć nagrania.
        Pusta suma w projekcie (np. autozapis przed jej policzeniem) oznacza
        brak weryfikacji. Zwraca nagranie i jego policzoną sumę (albo None).
        """
        ref = state.audio
        if ref is None:
            return None, None
        found = resolve_audio(ref, project_path)
        if found is None:
            found = self._ask_for_file(ref.name, ref.absolute_path, project_path)
            if found is None:
                return None, None
        if not ref.sha256:
            return found, None
        digest = self._hash_now(found)
        if digest == ref.sha256 or self._accept_changed(found):
            return found, digest
        return None, None

    def _ask_for_file(
        self, name: str, absolute_path: str, project_path: Path | None
    ) -> Path | None:
        answer = QMessageBox.question(
            self._parent,
            tr("session.audio_missing.title"),
            tr("session.audio_missing.text", name=name, path=absolute_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        start = str(project_path.parent) if project_path else ""
        chosen, _selected_filter = QFileDialog.getOpenFileName(
            self._parent,
            tr("session.audio_locate.dialog", name=name),
            start,
            audio_filter(),
        )
        return Path(chosen) if chosen else None

    def _accept_changed(self, found: Path) -> bool:
        answer = QMessageBox.question(
            self._parent,
            tr("session.audio_changed.title"),
            tr("session.audio_changed.text", name=found.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


__all__ = ["AudioLocator"]
