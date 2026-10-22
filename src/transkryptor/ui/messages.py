"""Wspólne komunikaty dla użytkownika (NFR-03)."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox, QWidget

from transkryptor.errors import AppError

logger = logging.getLogger(__name__)


def log_user_error(error: AppError, stacklevel: int = 1) -> None:
    """Wpis w dzienniku o błędzie pokazanym użytkownikowi (bez jego treści).

    Miejsce wywołania (moduł, funkcja, wiersz) wskazuje operację, a łańcuch
    przyczyn — źródło błędu.
    """
    logger.warning(
        "Error shown to the user: %s",
        type(error).__name__,
        exc_info=error,
        stacklevel=stacklevel + 1,
    )


def show_error(parent: QWidget, title: str, error: AppError) -> None:
    """Zrozumiały komunikat błędu z podpowiedzią, jak ponowić działanie."""
    log_user_error(error, stacklevel=2)
    message = error.user_message
    if error.retry_hint:
        message += f"\n\n{error.retry_hint}"
    QMessageBox.warning(parent, title, message)
