"""Blokada uśpienia komputera i wygaszacza ekranu na czas długiej pracy.

Transkrypcja godzinnego nagrania trwa długo; gdy użytkownik odejdzie od
komputera, system włączał wygaszacz i usypiał komputer, a transkrypcja
stawała. Na czas transkrypcji program prosi system, żeby tego nie robił:

- Windows: ``SetThreadExecutionState`` (komputer i ekran pozostają włączone);
- Linux: ``org.freedesktop.ScreenSaver.Inhibit`` przez D-Bus (KDE, GNOME
  i inne środowiska) - blokuje wygaszacz i uśpienie z bezczynności.

Blokada jest „najlepszego wysiłku”: gdy system jej nie obsługuje, praca
biegnie dalej bez niej. Po zakończeniu (także błędzie i anulowaniu) program
ją zwalnia; zamknięcie programu zwalnia ją zawsze.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Protocol

logger = logging.getLogger(__name__)

APPLICATION_NAME = "Transkryptor"

# Windows: flagi ``SetThreadExecutionState``.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

SCREENSAVER_SERVICE = "org.freedesktop.ScreenSaver"
SCREENSAVER_PATH = "/org/freedesktop/ScreenSaver"
# Własne połączenie z magistralą sesji: rozłączenie zwalnia blokadę bez
# ``UnInhibit`` (PySide nie przekaże ciasteczka jako typu ``u`` D-Bus).
DBUS_CONNECTION_NAME = "transkryptor-keep-awake"


class AwakeBackend(Protocol):
    """Systemowa blokada uśpienia: ``acquire`` - True, gdy się udało."""

    def acquire(self, reason: str) -> bool: ...

    def release(self) -> None: ...


class NullBackend:
    """System bez obsługiwanej blokady (np. macOS, brak D-Bus)."""

    def acquire(self, reason: str) -> bool:
        return False

    def release(self) -> None:
        pass


class WindowsBackend:
    """``SetThreadExecutionState`` z wątku okna (blokada trwa do zwolnienia)."""

    def acquire(self, reason: str) -> bool:
        return _set_execution_state(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )

    def release(self) -> None:
        _set_execution_state(ES_CONTINUOUS)


def _set_execution_state(flags: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadExecutionState.restype = ctypes.c_uint
        return bool(kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))
    return False


class DBusScreenSaverBackend:
    """``org.freedesktop.ScreenSaver.Inhibit`` na osobnym połączeniu D-Bus."""

    def __init__(self) -> None:
        self._connected = False

    def acquire(self, reason: str) -> bool:
        from PySide6.QtDBus import (
            QDBusConnection,
            QDBusInterface,
            QDBusMessage,
        )

        bus = QDBusConnection.connectToBus(
            QDBusConnection.BusType.SessionBus, DBUS_CONNECTION_NAME
        )
        if not bus.isConnected():
            QDBusConnection.disconnectFromBus(DBUS_CONNECTION_NAME)
            return False
        self._connected = True
        interface = QDBusInterface(
            SCREENSAVER_SERVICE, SCREENSAVER_PATH, SCREENSAVER_SERVICE, bus
        )
        reply = interface.call("Inhibit", APPLICATION_NAME, reason)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            logger.info("Screen saver inhibit unavailable: %s", reply.errorMessage())
            self.release()
            return False
        return True

    def release(self) -> None:
        if not self._connected:
            return
        from PySide6.QtDBus import QDBusConnection

        QDBusConnection.disconnectFromBus(DBUS_CONNECTION_NAME)
        self._connected = False


def default_backend() -> AwakeBackend:
    """Blokada dla bieżącego systemu (testy podmieniają ją na ``NullBackend``)."""
    if sys.platform == "win32":
        return WindowsBackend()
    if sys.platform.startswith("linux"):
        return DBusScreenSaverBackend()
    return NullBackend()


class KeepAwake:
    """Wstrzymuje uśpienie i wygaszacz między ``hold`` a ``release``."""

    def __init__(self, backend: AwakeBackend | None = None) -> None:
        self._backend = backend if backend is not None else default_backend()
        self._held = False

    @property
    def held(self) -> bool:
        """Program prosi system o czuwanie (niezależnie od tego, czy się udało)."""
        return self._held

    def hold(self, reason: str) -> None:
        if self._held:
            return
        self._held = True
        try:
            acquired = self._backend.acquire(reason)
        except Exception:  # blokada nie może przerwać transkrypcji
            logger.warning("Sleep inhibit failed", exc_info=True)
            return
        logger.info("Sleep inhibit %s", "on" if acquired else "unavailable")

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            self._backend.release()
        except Exception:  # zwolnienie blokady nie może przerwać pracy
            logger.warning("Sleep inhibit release failed", exc_info=True)
