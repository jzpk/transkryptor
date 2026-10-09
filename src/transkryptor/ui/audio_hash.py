"""Suma SHA-256 nagrania liczona w tle (PERF-03).

Nagranie terenowe ma setki MB, więc skrót liczony w wątku UI zamrażał okno
na sekundy przy imporcie nagrania i otwieraniu projektu. ``HashThread``
liczy go w tle, a :func:`wait_for` czeka na wynik tam, gdzie jest
potrzebny od razu (zapis projektu, sprawdzenie nagrania przy otwieraniu),
nie blokując odświeżania okna.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Qt, QThread
from PySide6.QtWidgets import QProgressDialog, QWidget

from transkryptor.document.project import file_sha256

# (ścieżka, should_cancel) → suma szesnastkowa; przerwanie → InterruptedError.
HashFunction = Callable[..., str]

# Krótkie liczenie kończy się bez migania okna postępu.
PROGRESS_DELAY_MS = 400
WAIT_STEP_MS = 30


class HashThread(QThread):
    """Liczy SHA-256 pliku; ``digest`` to wynik albo None (błąd, przerwanie)."""

    def __init__(
        self,
        path: Path,
        hash_impl: HashFunction = file_sha256,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.digest: str | None = None
        self._hash_impl = hash_impl

    def run(self) -> None:
        try:
            self.digest = self._hash_impl(
                self.path, should_cancel=self.isInterruptionRequested
            )
        except (OSError, InterruptedError):
            self.digest = None


def wait_for(thread: QThread, parent: QWidget, label: str) -> None:
    """Czeka na koniec wątku, obsługując zdarzenia (okno się odświeża).

    Gdy liczenie trwa dłużej niż ``PROGRESS_DELAY_MS``, pokazuje okno
    postępu bez przycisku anulowania.
    """
    if thread.wait(WAIT_STEP_MS):
        return
    dialog = QProgressDialog(label, "", 0, 0, parent)
    dialog.setCancelButton(None)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumDuration(PROGRESS_DELAY_MS)
    try:
        while not thread.wait(WAIT_STEP_MS):
            QCoreApplication.processEvents(
                QEventLoop.ProcessEventsFlag.AllEvents, WAIT_STEP_MS
            )
    finally:
        dialog.close()
        dialog.deleteLater()
