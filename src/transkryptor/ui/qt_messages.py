"""Komunikaty Qt w dzienniku programu.

Bez własnej obsługi Qt pisze komunikaty (np. ``qt.svg.draw``,
``qt.multimedia.ffmpeg``) tylko na konsolę, której zwykły użytkownik nie
widzi - a w dzienniku z raportem błędu ich brakowało. Ten moduł przekierowuje
je do ``logging`` (logger ``transkryptor.qt``) z kategorią Qt, a ostrzeżenia
uzupełnia o aktywne okno i widżet z fokusem, żeby dało się ustalić, co je
wywołało.

Informacje i komunikaty diagnostyczne trafiają tylko do dziennika;
ostrzeżenia i błędy - także na konsolę (deweloper uruchamiający ``run.sh``
dalej je widzi).
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import TextIO

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

logger = logging.getLogger("transkryptor.qt")

_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def install(console: TextIO | None = None) -> None:
    """Włącza przekierowanie komunikatów Qt (wołane raz, przy starcie)."""
    stream = console if console is not None else sys.stderr

    def handler(kind: QtMsgType, context: QMessageLogContext, message: str) -> None:
        handle_message(kind, context.category, message, stream)

    qInstallMessageHandler(handler)


def uninstall() -> None:
    """Przywraca domyślną obsługę Qt (testy)."""
    qInstallMessageHandler(None)


def handle_message(
    kind: QtMsgType, category: str | None, message: str, console: TextIO | None
) -> None:
    """Zapisuje komunikat w dzienniku; ostrzeżenia także na ``console``."""
    level = _LEVELS.get(kind, logging.WARNING)
    text = f"{category}: {message}" if category and category != "default" else message
    if level >= logging.WARNING:
        where = _ui_context()
        logger.log(level, "%s%s", text, f" [{where}]" if where else "")
        if console is not None:
            # Zamknięta konsola (np. program bez terminala) nie przerywa pracy.
            with contextlib.suppress(OSError, ValueError):
                print(text, file=console, flush=True)
    else:
        logger.log(level, "%s", text)


def _ui_context() -> str:
    """Aktywne okno i widżet z fokusem - wskazówka, skąd przyszło ostrzeżenie."""
    if QApplication.instance() is None:
        return ""
    try:
        parts = [
            f"{label}={_describe(widget)}"
            for label, widget in (
                ("window", QApplication.activeWindow()),
                ("focus", QApplication.focusWidget()),
            )
            if widget is not None
        ]
    except RuntimeError:  # obiekt w trakcie niszczenia
        return ""
    return ", ".join(parts)


def _describe(widget: object) -> str:
    name = type(widget).__name__
    object_name = getattr(widget, "objectName", lambda: "")()
    return f"{name}#{object_name}" if object_name else name
