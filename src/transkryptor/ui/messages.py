"""Wspólne komunikaty dla użytkownika (NFR-03)."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from transkryptor.errors import AppError


def show_error(parent: QWidget, title: str, error: AppError) -> None:
    """Zrozumiały komunikat błędu z podpowiedzią, jak ponowić działanie."""
    message = error.user_message
    if error.retry_hint:
        message += f"\n\n{error.retry_hint}"
    QMessageBox.warning(parent, title, message)
