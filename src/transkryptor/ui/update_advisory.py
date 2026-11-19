"""Okno ostrzeżenia o luce bezpieczeństwa w bieżącej wersji programu.

Treść pochodzi z podpisanego ``advisory.json`` (``update/advisory.py``).
Mimo podpisu jest traktowana jak zwykły tekst: znaki HTML są zamieniane na
encje, więc nie da się nią wstawić odnośników ani formatowania.
"""

from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QMessageBox, QWidget

from transkryptor import __version__
from transkryptor.i18n import current_language, tr
from transkryptor.update.advisory import Advisory


def advisory_html(advisory: Advisory, closing: str) -> str:
    """Treść okna jako HTML z samym tekstem (akapity, bez znaczników z pliku)."""
    message = advisory.message(current_language()) or tr(
        "update.advisory.default", version=__version__
    )
    paragraphs = [message, closing]
    return "".join(
        "<p>" + escape(text).replace("\n", "<br>") + "</p>" for text in paragraphs
    )


def warn_about_advisory(
    parent: QWidget, advisory: Advisory, *, can_install: bool
) -> bool:
    """Pokazuje ostrzeżenie; True, gdy użytkownik chce zainstalować teraz."""
    title = tr("update.advisory.title")
    if can_install:
        answer = QMessageBox.question(
            parent,
            title,
            advisory_html(advisory, tr("update.advisory.install")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes
    QMessageBox.warning(
        parent, title, advisory_html(advisory, tr("update.advisory.manual"))
    )
    return False
