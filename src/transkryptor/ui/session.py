"""Stan sesji: dokument, nowy dokument, import nagrania i ochrona pracy.

``SessionController`` jest właścicielem modelu ``Document`` bieżącej sesji
i pilnuje, by niewyeksportowane zmiany nie zginęły bez potwierdzenia
(REQ-09, ACC-10) — przy nowym dokumencie, imporcie nagrania i zamknięciu.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QDate, QObject
from PySide6.QtWidgets import QDateEdit, QLineEdit, QMessageBox, QWidget

from transkryptor.audio.player import AudioPlayer
from transkryptor.document.model import Document
from transkryptor.errors import AppError
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.messages import show_error
from transkryptor.ui.player_bar import PlayerBar

DISCARD_TITLE = "Niewyeksportowane zmiany"
DISCARD_TEXT = (
    "Transkrypcja zawiera zmiany, które nie zostały wyeksportowane. "
    "Zamknięcie lub rozpoczęcie nowej pracy spowoduje ich utratę."
)

STATUS_CLEAN = "Brak niewyeksportowanych zmian"
STATUS_DIRTY = "Niewyeksportowane zmiany — eksportuj DOCX (Ctrl+E)"


class SessionController(QObject):
    """Dokument sesji i operacje, które mogą go porzucić."""

    def __init__(
        self,
        dialog_parent: QWidget,
        editor: TranscriptionEditor,
        player: AudioPlayer,
        player_bar: PlayerBar,
        asr_panel: AsrPanel,
        author_edit: QLineEdit,
        date_edit: QDateEdit,
        on_reset: Callable[[], None],
    ) -> None:
        super().__init__(dialog_parent)
        self.document = Document()
        self._parent = dialog_parent
        self._editor = editor
        self._player = player
        self._player_bar = player_bar
        self._asr_panel = asr_panel
        self._author_edit = author_edit
        self._date_edit = date_edit
        self._on_reset = on_reset

    def maybe_discard_changes(self) -> bool:
        """Pyta o zgodę na utratę niewyeksportowanych zmian.

        Zwraca True, gdy można kontynuować operację (brak zmian albo
        użytkownik potwierdził odrzucenie), False, gdy użytkownik anulował.
        """
        if not self.document.is_dirty:
            return True
        answer = QMessageBox.question(
            self._parent,
            DISCARD_TITLE,
            DISCARD_TEXT,
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def sync_metadata(self) -> None:
        self.document.set_metadata(
            self._author_edit.text(), self._date_edit.date().toString("yyyy-MM-dd")
        )

    def new_document(self) -> None:
        if not self.maybe_discard_changes():
            return
        self._player.stop_and_unload()
        self._player_bar.reset()
        self._asr_panel.set_audio_available(False)
        self._editor.blockSignals(True)
        self._editor.clear()
        self._editor.blockSignals(False)
        self._author_edit.clear()
        self._date_edit.setDate(QDate.currentDate())
        self.document = Document()
        self._on_reset()

    def import_audio(self, path: str) -> None:
        if not self.maybe_discard_changes():
            return
        try:
            self._player.load(path)
        except AppError as error:
            show_error(self._parent, "Import nagrania", error)
            return
        self._player_bar.reset()
        self._asr_panel.set_audio_available(True)

    def can_close(self) -> bool:
        """ACC-10: zamknięcie po potwierdzeniu i bez działającej transkrypcji."""
        if self._asr_panel.is_transcribing():
            # Działający QThread nie może zostać zniszczony razem z oknem.
            QMessageBox.information(
                self._parent,
                "Transkrypcja w toku",
                "Najpierw anuluj transkrypcję albo poczekaj na jej zakończenie.",
            )
            return False
        if not self.maybe_discard_changes():
            return False
        self._player.stop_and_unload()
        return True
