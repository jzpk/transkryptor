"""Rozpakowanie serii nagrań z ZIP-a w wątku w tle (``corpus/series.py``).

Okno główne jest na ten czas zablokowane: nakładka z postępem (nagrania
i megabajty) i przyciskiem „Przerwij”, a wejście poza tym przyciskiem
odrzuca ``InputBlocker``. Wynik albo błąd trafia do wątku UI po końcu
rozpakowania; przerwane rozpakowanie nie zostawia uciętego pliku.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget

from transkryptor.corpus.series import (
    ExtractionCancelled,
    ExtractStatus,
    SeriesImport,
    extract_series,
)
from transkryptor.i18n import tr
from transkryptor.ui.busy_overlay import BusyOverlay, InputBlocker

_MB = 1024 * 1024


class _ExtractThread(QThread):
    """``extract_series`` w wątku w tle, z postępem i przerwaniem."""

    # Obiekt, nie int - liczba bajtów przekracza zakres int w C++.
    progressed = Signal(object)

    def __init__(self, archive: Path, folder: Path, parent: QObject) -> None:
        super().__init__(parent)
        self._archive = archive
        self._folder = folder
        self._cancel = threading.Event()
        self.result: SeriesImport | None = None
        self.error: BaseException | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            self.result = extract_series(self._archive, self._folder, self._progress)
        except ExtractionCancelled:
            pass
        except Exception as error:  # noqa: BLE001 - przekazywany do wątku UI
            self.error = error

    def _progress(self, status: ExtractStatus) -> bool:
        self.progressed.emit(status)
        return not self._cancel.is_set()


class SeriesImporter(QObject):
    """Rozpakowanie serii w tle z nakładką postępu nad oknem ``host``.

    ``finished(result, error)``: ``SeriesImport`` albo None (przerwane
    lub błąd), a ``error`` - wyjątek albo None.
    """

    finished = Signal(object, object)

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.overlay = BusyOverlay(host)
        self.overlay.setObjectName("series_import_overlay")
        self.overlay.cancel_requested.connect(self.cancel)
        self._blocker = InputBlocker((self.overlay.cancel_button,), self)
        self._thread: _ExtractThread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def start(self, archive: Path, folder: Path) -> bool:
        """Zaczyna rozpakowanie; False - poprzednie jeszcze trwa."""
        if self._thread is not None:
            return False
        thread = _ExtractThread(archive, folder, self)
        thread.progressed.connect(self._on_progress)
        thread.finished.connect(self._finish)
        self._thread = thread
        self._blocker.start()
        self.overlay.start(tr("series.import.busy", name=archive.name))
        thread.start()
        return True

    def cancel(self) -> None:
        if self._thread is not None:
            self._thread.cancel()

    def wait(self, timeout_ms: int = 30_000) -> None:
        """Czeka na koniec rozpakowania i obsługuje wynik (testy)."""
        thread = self._thread
        if thread is not None and thread.wait(timeout_ms):
            QApplication.sendPostedEvents()
            QApplication.processEvents()

    def _on_progress(self, status: ExtractStatus) -> None:
        if self._thread is None or self._thread.cancelled:
            return
        fraction = status.bytes_done / status.bytes_total if status.bytes_total else 0
        self.overlay.set_detail(
            fraction,
            tr(
                "series.import.progress",
                done=status.files_done,
                total=status.files_total,
                mb_done=status.bytes_done // _MB,
                mb_total=-(-status.bytes_total // _MB),
            ),
        )

    def _finish(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._thread = None
        self.overlay.stop()
        self._blocker.stop()
        thread.deleteLater()
        self.finished.emit(thread.result, thread.error)


__all__ = ["SeriesImporter"]
