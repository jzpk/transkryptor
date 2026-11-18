"""Praca okna „Korpus” w wątku w tle: skan folderu, wyszukiwanie, formy."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

# ``progress(done, total)`` z wątku w tle; False - przerwij pracę.
Progress = Callable[[int, int], bool]


class CorpusTask(QThread):
    """Praca w wątku w tle z postępem i przerwaniem.

    ``work`` dostaje funkcję postępu - zwraca ona False po :meth:`cancel`.
    Wynik albo wyjątek odbiera wątek UI po sygnale ``finished``.
    """

    progressed = Signal(int, int)

    def __init__(self, work: Callable[[Progress], object], parent: QObject) -> None:
        super().__init__(parent)
        self._work = work
        self._cancel = threading.Event()
        self.result: object = None
        self.error: BaseException | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            self.result = self._work(self._progress)
        except Exception as error:  # noqa: BLE001 - przekazywany do wątku UI
            self.error = error

    def _progress(self, done: int, total: int) -> bool:
        self.progressed.emit(done, total)
        return not self._cancel.is_set()


__all__ = ["CorpusTask", "Progress"]
