"""Okno „Co nowego”: historia zmian aplikacji (``CHANGELOG.md``)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from transkryptor import __version__
from transkryptor.changes import changelog_text, history_markdown
from transkryptor.i18n import POLISH, current_language, tr
from transkryptor.ui.theme import set_props


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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.language_note)
        layout.addWidget(self.browser, stretch=1)
        layout.addWidget(buttons)
        self.resize(640, 600)
