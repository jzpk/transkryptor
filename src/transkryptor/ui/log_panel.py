"""Zakładka „Dziennik logów” w ustawieniach (dla zaawansowanych użytkowników).

Pokazuje folder dziennika błędów (``diagnostics``) z odnośnikiem, który go
otwiera, oraz formularz zgłoszenia problemu na GitHubie w przeglądarce.
Zakładka nie ma ustawień - niczego nie zapisuje.
"""

from __future__ import annotations

import contextlib
import html
import platform
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from transkryptor import __version__, diagnostics
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props
from transkryptor.update.releases import GITHUB_REPO

NEW_ISSUE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"


def new_issue_url() -> str:
    """Formularz zgłoszenia z wersją programu i systemu (bez danych osobowych)."""
    body = (
        f"Transkryptor {__version__}\n"
        f"OS: {platform.platform()}\n\n"
        f"<!-- Describe the problem and attach {diagnostics.LOG_FILE_NAME} -->\n"
    )
    return f"{NEW_ISSUE_URL}?{urlencode({'body': body})}"


def log_folder() -> Path:
    """Folder dziennika; tworzony, gdy dziennik jeszcze nie powstał."""
    folder = diagnostics.active_log_dir() or diagnostics.log_dir()
    with contextlib.suppress(OSError):
        folder.mkdir(parents=True, exist_ok=True)
    return folder


class LogPanel(QWidget):
    """Informacja o dzienniku, odnośnik do jego folderu i zgłoszenie problemu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        folder = diagnostics.active_log_dir() or diagnostics.log_dir()

        intro = QLabel(tr("settings.logs.intro", file=diagnostics.LOG_FILE_NAME))
        intro.setWordWrap(True)
        privacy = QLabel(tr("settings.logs.privacy"))
        privacy.setWordWrap(True)
        set_props(privacy, role="muted")

        caption = QLabel(tr("settings.logs.folder"))
        self.folder_link = QLabel(
            f'<a href="{html.escape(QUrl.fromLocalFile(str(folder)).toString())}">'
            f"{html.escape(str(folder))}</a>"
        )
        self.folder_link.setTextFormat(Qt.TextFormat.RichText)
        self.folder_link.setWordWrap(True)
        self.folder_link.setToolTip(tr("settings.logs.open"))
        self.folder_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.folder_link.linkActivated.connect(lambda _url: self.open_folder())

        self.open_button = QPushButton(tr("settings.logs.open"))
        self.open_button.clicked.connect(self.open_folder)
        self.report_button = QPushButton(tr("settings.logs.report"))
        self.report_button.setToolTip(tr("settings.logs.report.tooltip"))
        self.report_button.clicked.connect(self.report_problem)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.report_button)
        buttons.addStretch(1)

        # Marginesy i odstępy jak w formularzach pozostałych zakładek.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addWidget(privacy)
        layout.addSpacing(6)
        layout.addWidget(caption)
        layout.addWidget(self.folder_link)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_folder())))

    def report_problem(self) -> None:
        QDesktopServices.openUrl(QUrl(new_issue_url()))
