"""Przyciski w lewym dolnym rogu okna: historia zmian i formularz zgłoszeń.

Na czas krótkiego komunikatu (``showMessage``) pasek stanu chowa przyciski
i pokazuje tekst.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QToolButton, QWidget

from transkryptor import __version__
from transkryptor.feedback import report_form_url
from transkryptor.i18n import tr
from transkryptor.ui import icons
from transkryptor.ui.changelog_dialog import ChangelogDialog


def status_button(name: str, text: str, tooltip: str, icon: str) -> QToolButton:
    """Płaski przycisk paska stanu z ikoną i tekstem (bez fokusu klawiatury)."""
    button = QToolButton()
    button.setObjectName(name)
    button.setText(text)
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    icons.set_icon(button, icon, "text_muted", "text_muted")
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return button


def changelog_button(window: QWidget) -> QToolButton:
    """„Co nowego” - okno historii zmian."""
    button = status_button(
        "changelog_button",
        tr("changelog.button", version=__version__),
        tr("changelog.button.tooltip"),
        "info",
    )
    button.clicked.connect(lambda: ChangelogDialog(window).exec())
    return button


def report_button() -> QToolButton:
    """Formularz zgłoszeń na stronie programu - bez konta na GitHubie."""
    button = status_button(
        "report_button", tr("report.button"), tr("report.button.tooltip"), "comment"
    )
    button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(report_form_url())))
    return button
