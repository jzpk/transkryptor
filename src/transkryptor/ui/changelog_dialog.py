"""Okno „Co nowego”: historia zmian aplikacji (``CHANGELOG.md``).

Okno pokazuje też, jak zgłosić problem: otwiera folder dziennika błędów
(``diagnostics``) i formularz zgłoszenia na GitHubie w przeglądarce.
"""

from __future__ import annotations

import platform
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from transkryptor import __version__, diagnostics
from transkryptor.changes import changelog_text, history_markdown
from transkryptor.i18n import POLISH, current_language, tr
from transkryptor.ui.theme import set_props
from transkryptor.update.releases import GITHUB_REPO

NEW_ISSUE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"


def new_issue_url() -> str:
    """Formularz zgłoszenia z wersją programu i systemu (bez danych osobowych)."""
    body = (
        f"Transkryptor {__version__}\n"
        f"OS: {platform.platform()}\n\n"
        "<!-- Describe the problem and attach transkryptor.log -->\n"
    )
    return f"{NEW_ISSUE_URL}?{urlencode({'body': body})}"


def log_folder() -> Path:
    """Folder dziennika do otwarcia; tworzony, gdy dziennik jeszcze nie powstał."""
    folder = diagnostics.active_log_dir() or diagnostics.log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder


class ChangelogDialog(QDialog):
    """Historia zmian od najnowszej wersji; tylko do odczytu."""

    def __init__(self, parent: QWidget | None = None, text: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("changelog_dialog")
        self.setWindowTitle(tr("changelog.title"))

        header = QLabel(tr("changelog.header", version=__version__))
        set_props(header, role="title")
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        source = changelog_text() if text is None else text
        if source is None:
            self.browser.setPlainText(tr("changelog.missing"))
        else:
            self.browser.setMarkdown(
                history_markdown(source, tr("changelog.unreleased"))
            )
        self.language_note = QLabel(tr("changelog.polish_only"))
        self.language_note.setWordWrap(True)
        set_props(self.language_note, role="muted")
        self.language_note.setVisible(current_language() != POLISH)

        self.report_note = QLabel(
            tr("changelog.report.note", file=diagnostics.LOG_FILE_NAME)
        )
        self.report_note.setWordWrap(True)
        set_props(self.report_note, role="muted")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.open_logs_button = buttons.addButton(
            tr("changelog.report.open_logs"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.open_logs_button.clicked.connect(self._on_open_logs)
        self.report_button = buttons.addButton(
            tr("changelog.report.issue"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.report_button.setToolTip(tr("changelog.report.issue.tooltip"))
        self.report_button.clicked.connect(self._on_report)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.language_note)
        layout.addWidget(self.browser, stretch=1)
        layout.addWidget(self.report_note)
        layout.addWidget(buttons)
        self.resize(640, 600)

    def _on_open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_folder())))

    def _on_report(self) -> None:
        QDesktopServices.openUrl(QUrl(new_issue_url()))
