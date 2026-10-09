"""Autozapis bieżącej pracy i odzyskiwanie po awarii.

Co interwał z ustawień (sekcja „Projekt”) ``AutosaveController`` zapisuje
stan pracy w formacie projektu do ``autosave_dir() / <id sesji>.transkr``
— tylko, gdy dokument zmienił się od ostatniego autozapisu i ma niezapisane
zmiany. Autozapis nie zmienia ``saved_revision`` i nigdy nie pisze do pliku
projektu użytkownika. Na czas ASR jest wstrzymany; zaległy zapis wykonuje
się po zakończeniu transkrypcji.

Każda sesja trzyma ``QLockFile`` ``<id sesji>.lock``. Plik autozapisu, którego
blokady nikt nie trzyma (proces zakończył się awaryjnie), jest osierocony
i aplikacja proponuje jego odzyskanie przy starcie. Poprawne zamknięcie
i „Nowy dokument” usuwają plik autozapisu sesji.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor import paths
from transkryptor.document.model import Document
from transkryptor.document.project import (
    PROJECT_SUFFIX,
    ProjectState,
    dumps,
    load_project,
    write_atomic,
)
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.settings import ProjectSettings
from transkryptor.ui.layout import words_label

LOCK_SUFFIX = ".lock"


class AutosaveController(QObject):
    """Okresowa kopia stanu pracy w katalogu danych aplikacji."""

    def __init__(
        self,
        capture: Callable[[], ProjectState],
        document: Callable[[], Document],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture = capture
        self._document = document
        self.session_id = uuid.uuid4().hex
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.save_now)
        self._enabled = False
        self._paused = False
        self._pending = False
        self._last_document: Document | None = None
        self._last_revision = -1
        self._lock: QLockFile | None = None

    @property
    def directory(self) -> Path:
        return paths.autosave_dir()

    @property
    def path(self) -> Path:
        return self.directory / f"{self.session_id}{PROJECT_SUFFIX}"

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def configure(self, settings: ProjectSettings) -> None:
        """Włącza/wyłącza autozapis i ustawia interwał (bez restartu)."""
        self._enabled = settings.autosave_enabled
        if settings.autosave_enabled:
            self._timer.start(settings.autosave_interval_s * 1000)
        else:
            self._timer.stop()
            self.discard()

    def save_now(self) -> bool:
        """Zapisuje kopię, gdy jest co zapisać; zwraca True po zapisie."""
        if not self._enabled:
            return False
        if self._paused:
            self._pending = True
            return False
        document = self._document()
        unchanged = (
            document is self._last_document and document.revision == self._last_revision
        )
        if unchanged or document.revision == 0 or not document.is_unsaved:
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._ensure_lock()
            write_atomic(self.path, dumps(self._capture()).encode("utf-8"))
        except (OSError, AppError):
            # Autozapis jest siatką bezpieczeństwa: błąd nie przerywa pracy,
            # kolejna próba nastąpi przy następnym interwale.
            return False
        self._last_document = document
        self._last_revision = document.revision
        return True

    def pause(self) -> None:
        """Wstrzymuje autozapis (np. na czas ASR)."""
        self._paused = True

    def resume(self) -> None:
        """Wznawia autozapis i wykonuje zaległy zapis."""
        self._paused = False
        if self._pending:
            self._pending = False
            self.save_now()

    def discard(self) -> None:
        """Usuwa plik autozapisu sesji (praca zapisana albo porzucona)."""
        self.path.unlink(missing_ok=True)
        self._last_document = None
        self._last_revision = -1

    def shutdown(self) -> None:
        """Poprawne zamknięcie: bez pliku autozapisu i bez blokady."""
        self._timer.stop()
        self.discard()
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def _ensure_lock(self) -> None:
        if self._lock is None:
            lock = _lock_file(self.path)
            if lock.tryLock(0):
                self._lock = lock


# --- odzyskiwanie -------------------------------------------------------------


@dataclass
class RecoveryCandidate:
    """Osierocony plik autozapisu; ``state`` None = pliku nie da się odczytać."""

    path: Path
    modified: datetime
    state: ProjectState | None
    lock: QLockFile

    @property
    def label(self) -> str:
        when = self.modified.strftime("%d.%m.%Y %H:%M")
        if self.state is None:
            return tr("recovery.unreadable", when=when)
        audio = self.state.audio.name if self.state.audio else tr("recovery.no_audio")
        words = self.state.word_count
        return f"{when} — {audio} — {words} {words_label(words)}"

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
        self.release()

    def release(self) -> None:
        self.lock.unlock()


def find_orphans(directory: Path, own_session_id: str = "") -> list[RecoveryCandidate]:
    """Pliki autozapisu sesji, które się nie zakończyły (najnowsze pierwsze).

    Zwrócone kandydaty trzymają blokadę swoich plików — inna instancja nie
    zaproponuje ich równocześnie. Należy wywołać ``release`` albo ``remove``.
    """
    if not directory.is_dir():
        return []
    candidates: list[RecoveryCandidate] = []
    for path in directory.glob(f"*{PROJECT_SUFFIX}"):
        if path.stem == own_session_id:
            continue
        lock = _lock_file(path)
        if not lock.tryLock(0):
            continue  # sesja wciąż działa
        try:
            state: ProjectState | None = load_project(path)
        except AppError:
            state = None
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            lock.unlock()
            continue
        candidates.append(RecoveryCandidate(path, modified, state, lock))
    candidates.sort(key=lambda candidate: candidate.modified, reverse=True)
    return candidates


def _lock_file(path: Path) -> QLockFile:
    lock = QLockFile(str(path.with_suffix(LOCK_SUFFIX)))
    # Blokada trzymana przez całą sesję nie może się „przeterminować”;
    # blokadę po zakończonym procesie QLockFile rozpoznaje po PID.
    lock.setStaleLockTime(0)
    return lock


class RecoveryDialog(QDialog):
    """„Odzyskać pracę?” — lista osieroconych autozapisów.

    „Odzyskaj” zamyka okno z wybraną pozycją w ``chosen``; „Odrzuć” usuwa
    plik wybranej pozycji; „Później” zostawia pliki na następny start.
    """

    def __init__(
        self, candidates: list[RecoveryCandidate], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("recovery.title"))
        self.candidates = list(candidates)
        self.chosen: RecoveryCandidate | None = None

        intro = QLabel(
            tr("recovery.intro.one")
            if len(candidates) == 1
            else tr("recovery.intro.many")
        )
        intro.setWordWrap(True)
        self.list = QListWidget()
        for candidate in self.candidates:
            item = QListWidgetItem(candidate.label)
            item.setToolTip(str(candidate.path))
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())
        self.list.itemDoubleClicked.connect(lambda _item: self.recover_selected())

        buttons = QDialogButtonBox()
        self.recover_button: QPushButton = buttons.addButton(
            tr("recovery.recover"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.discard_button: QPushButton = buttons.addButton(
            tr("recovery.discard"), QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.later_button: QPushButton = buttons.addButton(
            tr("recovery.later"), QDialogButtonBox.ButtonRole.RejectRole
        )
        self.recover_button.clicked.connect(self.recover_selected)
        self.discard_button.clicked.connect(self.discard_selected)
        self.later_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.list)
        layout.addWidget(buttons)
        self.resize(520, 260)
        self._update_buttons()

    def _selected(self) -> RecoveryCandidate | None:
        row = self.list.currentRow()
        return self.candidates[row] if 0 <= row < len(self.candidates) else None

    def recover_selected(self) -> None:
        candidate = self._selected()
        if candidate is None or candidate.state is None:
            return
        self.chosen = candidate
        self.accept()

    def discard_selected(self) -> None:
        row = self.list.currentRow()
        candidate = self._selected()
        if candidate is None:
            return
        candidate.remove()
        del self.candidates[row]
        self.list.takeItem(row)
        if not self.candidates:
            self.reject()
            return
        self._update_buttons()

    def _update_buttons(self) -> None:
        candidate = self._selected()
        self.recover_button.setEnabled(
            candidate is not None and candidate.state is not None
        )
        self.discard_button.setEnabled(candidate is not None)
