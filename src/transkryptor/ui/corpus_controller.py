"""Okno „Korpus” w oknie głównym: bieżący projekt, przejścia i blokada.

Kontroler tworzy okno korpusu przy pierwszym otwarciu (domyślny folder to
folder bieżącego projektu) i dostarcza mu stan edytora jako projekt
korpusu. Przejście do trafienia w innym projekcie otwiera ten projekt
(z pytaniem o niezapisane zmiany) i zaznacza fragment w edytorze - o ile
tekst w tym miejscu nie zmienił się od wyszukiwania.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from transkryptor.audio.player import AudioPlayer
from transkryptor.corpus.projects import CorpusProject
from transkryptor.document.metadata import MetadataField
from transkryptor.i18n import tr
from transkryptor.ui.corpus_dialog import CorpusDialog, CorpusHost
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.session import SessionController


class CorpusController(QObject):
    def __init__(
        self,
        session: SessionController,
        editor: TranscriptionEditor,
        player: AudioPlayer,
        fields: Callable[[], tuple[MetadataField, ...]],
        recent_projects: Callable[[], list[str]],
        show_status: Callable[[str], None],
        window: QWidget,
    ) -> None:
        super().__init__(window)
        self._session = session
        self._editor = editor
        self._player = player
        self._fields = fields
        self._recent_projects = recent_projects
        self._show_status = show_status
        self._window = window
        self.dialog: CorpusDialog | None = None
        self._locked = False

    def open_dialog(self) -> CorpusDialog:
        """Pokazuje okno korpusu (przy pierwszym otwarciu skanuje folder)."""
        dialog = self.dialog
        if dialog is None:
            dialog = self.dialog = CorpusDialog(
                CorpusHost(
                    current_project=self.current_project,
                    fields=self._fields,
                    go_to=self.go_to,
                    pause_main=self._player.pause,
                ),
                self._window,
            )
            dialog.setEnabled(not self._locked)
            dialog.set_folder(self.default_folder())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def default_folder(self) -> Path | None:
        """Folder bieżącego projektu, a bez niego - ostatnio otwieranego."""
        if self._session.project_path is not None:
            return self._session.project_path.parent
        for recent in self._recent_projects():
            folder = Path(recent).parent
            if folder.is_dir():
                return folder
        return None

    def current_project(self) -> CorpusProject:
        """Bieżący dokument ze stanu edytora (z niezapisanymi zmianami)."""
        self._session.flush_editor()
        return CorpusProject(
            self._session.project_path,
            self._session.capture_state(),
            title=self._session.project_name or tr("corpus.current"),
        )

    def go_to(self, project: CorpusProject, start: int, end: int) -> bool:
        """Zaznacza fragment projektu w edytorze (otwiera projekt, gdy trzeba)."""
        if self._locked:
            return False
        if not self._is_current(project.path) and (
            project.path is None or not self._session.open_project(project.path)
        ):
            return False
        text = self._editor.plain_text()
        if text[start:end] != project.state.text[start:end] or end > len(text):
            self._show_status(tr("corpus.stale"))
            if self.dialog is not None:
                self.dialog.status_label.setText(tr("corpus.stale"))
            return False
        self._editor.setTextCursor(self._editor.track_range(start, end))
        self._editor.ensureCursorVisible()
        self._window.raise_()
        self._window.activateWindow()
        self._editor.setFocus()
        return True

    def _is_current(self, path: Path | None) -> bool:
        current = self._session.project_path
        if path is None:
            return True
        return current is not None and current.resolve() == path.resolve()

    @property
    def busy(self) -> bool:
        """Okno korpusu liczy coś w tle (interfejs jest zablokowany)."""
        return self.dialog is not None and self.dialog.busy

    def set_locked(self, locked: bool) -> None:
        """Na czas transkrypcji okno korpusu jest nieaktywne."""
        self._locked = locked
        if self.dialog is not None:
            self.dialog.setEnabled(not locked)

    def shutdown(self) -> None:
        if self.dialog is not None:
            self.dialog.shutdown()
