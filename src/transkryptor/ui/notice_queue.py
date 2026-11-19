"""Okna komunikatów pokazywane po kolei, nigdy jedno na drugim.

Przy starcie kilka źródeł chce coś pokazać naraz: odzyskanie pracy po
awarii, błędne reguły użytkownika, ostrzeżenie o luce bezpieczeństwa,
samouczek „Pierwsze kroki”. Każde z nich trafia do kolejki
(:meth:`NoticeQueue.post`) i rusza dopiero wtedy, gdy:

- poprzednie z kolejki się zakończyło (okna modalne wracają po zamknięciu),
- nie jest otwarte żadne inne okno modalne (np. ustawienia),
- okno nie jest zajęte (``busy``, np. trwa samouczek).

Kolejność to kolejność dodania. Komunikat pojawiający się później (np. po
pobraniu w tle) też czeka na swoją kolej zamiast przykryć otwarte okno.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# Co tyle sprawdzić ponownie, czy okno jest już wolne.
RETRY_MS = 500

Notice = Callable[[], object]


class NoticeQueue(QObject):
    """Kolejka komunikatów okna głównego (jeden naraz, w kolejności dodania)."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        busy: Callable[[], bool] = lambda: False,
    ) -> None:
        super().__init__(parent)
        self._busy = busy
        self._pending: deque[Notice] = deque()
        self._running = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)

    def post(self, notice: Notice) -> None:
        """Dodaje komunikat; pokaże się, gdy przyjdzie jego kolej."""
        self._pending.append(notice)
        if not self._timer.isActive():
            self._timer.start(0)

    @property
    def pending(self) -> int:
        return len(self._pending)

    def _is_free(self) -> bool:
        return QApplication.activeModalWidget() is None and not self._busy()

    def _next(self) -> None:
        if self._running or not self._pending:
            # Trwający komunikat po zamknięciu sam uruchomi następny.
            return
        if not self._is_free():
            self._timer.start(RETRY_MS)
            return
        notice = self._pending.popleft()
        self._running = True
        try:
            notice()
        except Exception:  # jeden błędny komunikat nie blokuje pozostałych
            logger.exception("Notice failed")
        finally:
            self._running = False
        if self._pending:
            self._timer.start(0)
