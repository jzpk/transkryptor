"""Okno komentarza recenzji: autor i treść (faza 14)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props


class CommentDialog(QDialog):
    """Autor (zapamiętywany przez wywołującego) i treść komentarza lub odpowiedzi."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        author: str = "",
        text: str = "",
        context: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.author_edit = QLineEdit(author)
        self.author_edit.setPlaceholderText(tr("comments.author.placeholder"))
        self.text_edit = QPlainTextEdit(text)
        self.text_edit.setPlaceholderText(tr("comments.text.placeholder"))
        self.text_edit.setTabChangesFocus(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.text_edit.textChanged.connect(self._update_ok)

        form = QFormLayout()
        form.addRow(tr("comments.author"), self.author_edit)
        layout = QVBoxLayout(self)
        if context:
            quote = QLabel(context)
            quote.setWordWrap(True)
            set_props(quote, role="muted")
            layout.addWidget(quote)
        layout.addLayout(form)
        layout.addWidget(self.text_edit, stretch=1)
        layout.addWidget(self.buttons)
        self.text_edit.setFocus()
        self._update_ok()

    def values(self) -> tuple[str, str]:
        """Autor i treść (bez odstępów na brzegach)."""
        return self.author_edit.text().strip(), self.text_edit.toPlainText().strip()

    def _update_ok(self) -> None:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        button.setEnabled(bool(self.text_edit.toPlainText().strip()))


def ask_comment(
    parent: QWidget | None, title: str, author: str, text: str = "", context: str = ""
) -> tuple[str, str] | None:
    """Pyta o autora i treść; None - anulowano."""
    dialog = CommentDialog(parent, title, author, text, context)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.values()
