"""Migawki projektu w oknie: zapis ręczny, automatyczny i historia.

„Zapisz migawkę…” zapisuje bieżący stan pracy z krótkim opisem. Migawki
automatyczne powstają przed ryzykownymi operacjami: wstawieniem szkicu ASR
(``ReviewController.draft_about_to_insert``), importem DOCX
(``SessionEvents.about_to_import``) i masową zmianą notacji
(``NotationController.bulk_change_started``) - kontroler tylko łączy te
sygnały. „Historia projektu…” otwiera listę migawek
(``ui/history_dialog.py``): porównanie z bieżącym stanem idzie przez
istniejące „Porównaj z…”, a przywrócenie najpierw zapisuje bieżący stan
jako migawkę, więc da się je cofnąć.

Format i katalog migawek: ``document/snapshots.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, SignalInstance
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from transkryptor.document import snapshots
from transkryptor.document.project import ProjectState, resolve_audio
from transkryptor.document.snapshots import (
    Snapshot,
    SnapshotStore,
    project_key,
    session_key,
)
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.history_dialog import (
    COMPARE,
    RESTORE,
    HistoryDialog,
    snapshot_date,
)
from transkryptor.ui.messages import show_error
from transkryptor.ui.session import SessionController

logger = logging.getLogger(__name__)

# Opisy migawek automatycznych (klucze tłumaczeń).
BEFORE_DRAFT = "snapshots.reason.draft"
BEFORE_IMPORT = "snapshots.reason.import"
BEFORE_BULK = "snapshots.reason.bulk"
BEFORE_RESTORE = "snapshots.reason.restore"


class SnapshotController(QObject):
    """Polecenia migawek i migawki automatyczne bieżącej sesji."""

    def __init__(
        self,
        parent: QWidget,
        session: SessionController,
        compare: Callable[[ProjectState, str], bool],
        audio_path: Callable[[], Path | None],
        show_status: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._session = session
        self._compare = compare
        self._audio_path = audio_path
        self._show_status = show_status
        self._store = SnapshotStore(self._directory())
        self.save_action = QAction(tr("snapshots.save"), parent)
        self.save_action.setToolTip(tr("snapshots.save.tooltip"))
        self.save_action.triggered.connect(lambda _checked=False: self.save_dialog())
        self.history_action = QAction(tr("snapshots.history"), parent)
        self.history_action.setToolTip(tr("snapshots.history.tooltip"))
        self.history_action.triggered.connect(lambda _checked=False: self.history())
        self.actions = (self.save_action, self.history_action)
        session.events.saved.connect(lambda: self._follow_project(move=True))
        session.events.state_changed.connect(lambda: self._follow_project())
        session.events.reset.connect(lambda: self._follow_project())
        session.events.about_to_import.connect(lambda: self.checkpoint(BEFORE_IMPORT))
        # Dialog podpisu migawki; testy podstawiają gotową odpowiedź.
        self.ask_label: Callable[[], str | None] = self._ask_label
        self.run_history: Callable[[HistoryDialog], int] = lambda d: d.exec()

    @property
    def store(self) -> SnapshotStore:
        return self._store

    def watch(
        self, draft_about_to_insert: SignalInstance, bulk_change_started: SignalInstance
    ) -> None:
        """Migawki automatyczne przed szkicem ASR i masową zmianą notacji."""
        draft_about_to_insert.connect(lambda: self.checkpoint(BEFORE_DRAFT))
        bulk_change_started.connect(lambda: self.checkpoint(BEFORE_BULK))

    # --- zapis -----------------------------------------------------------

    def save_dialog(self) -> bool:
        """„Zapisz migawkę…”: opis od użytkownika i zapis bieżącego stanu."""
        label = self.ask_label()
        if label is None:
            return False
        return self.save(label.strip() or tr("snapshots.default_label")) is not None

    def save(self, label: str, automatic: bool = False) -> Snapshot | None:
        try:
            snapshot = self._store.save(self._session.capture_state(), label, automatic)
        except AppError as error:
            if automatic:
                logger.warning("Automatic snapshot failed: %s", error)
                self._show_status(tr("snapshots.auto_failed"))
            else:
                show_error(self._parent, tr("snapshots.save.error"), error)
            return None
        if not automatic:
            self._show_status(tr("snapshots.saved", label=label))
        return snapshot

    def checkpoint(self, reason: str) -> Snapshot | None:
        """Migawka automatyczna przed ryzykowną operacją (pusta praca - bez)."""
        if not self._session.document.text.strip():
            return None
        return self.save(tr(reason), automatic=True)

    # --- historia --------------------------------------------------------

    def history(self) -> None:
        dialog = HistoryDialog(self._store, self._parent)
        result = self.run_history(dialog)
        snapshot = dialog.chosen
        if snapshot is None:
            return
        if result == COMPARE:
            self.compare(snapshot)
        elif result == RESTORE:
            self.restore(snapshot)

    def compare(self, snapshot: Snapshot) -> bool:
        state = self._load(snapshot)
        if state is None:
            return False
        name = tr("snapshots.compare_name", date=snapshot_date(snapshot))
        return self._compare(state, name)

    def restore(self, snapshot: Snapshot, confirm: bool = True) -> bool:
        """Przywraca migawkę; bieżący stan zostaje zapisany jako migawka."""
        state = self._load(snapshot)
        if state is None:
            return False
        if confirm:
            answer = QMessageBox.question(
                self._parent,
                tr("snapshots.restore.title"),
                tr("snapshots.restore.text", date=snapshot_date(snapshot)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        # Bez migawki bieżącej pracy przywrócenie nie dałoby się cofnąć.
        saved = self.save(tr(BEFORE_RESTORE), automatic=True)
        if saved is None and self._session.document.text.strip():
            return False
        audio, sha256 = self._audio_for(state)
        self._session.apply_state(
            state, self._session.project_path, audio, saved=False, audio_sha256=sha256
        )
        self._show_status(tr("snapshots.restored", date=snapshot_date(snapshot)))
        return True

    def _load(self, snapshot: Snapshot) -> ProjectState | None:
        try:
            return self._store.load(snapshot)
        except AppError as error:
            show_error(self._parent, tr("snapshots.history.title"), error)
            return None

    def _audio_for(self, state: ProjectState) -> tuple[Path | None, str | None]:
        """Nagranie migawki: bieżące (ta sama suma) albo plik z odwołania."""
        ref = state.audio
        if ref is None:
            return None, None
        current = self._audio_path()
        if current is not None and ref.sha256 == self._session.audio_sha256:
            return current, ref.sha256 or None
        found = resolve_audio(ref, self._session.project_path)
        return found, None

    # --- katalog migawek -------------------------------------------------

    def _directory(self) -> Path:
        path = self._session.project_path
        key = (
            project_key(path)
            if path is not None
            else session_key(self._session.autosave.session_id)
        )
        # Przez moduł - testy podmieniają ``snapshots_root``.
        return snapshots.snapshots_root() / key

    def _follow_project(self, move: bool = False) -> None:
        """Katalog migawek bieżącego projektu.

        Zapis pracy bez pliku projektu (``move``) zabiera migawki sesji do
        katalogu nowego projektu; otwarcie innego projektu ich nie przenosi.
        """
        directory = self._directory()
        if directory == self._store.directory:
            return
        previous = self._store
        if move and previous.directory.name.startswith(session_key("")):
            self._store = previous.move_to(directory)
        else:
            self._store = SnapshotStore(directory)

    def _ask_label(self) -> str | None:
        label, accepted = QInputDialog.getText(
            self._parent, tr("snapshots.save.title"), tr("snapshots.save.prompt")
        )
        return label if accepted else None
