"""Panel komentarzy recenzji (faza 14, REQ-27).

Drzewo o jednym poziomie: komentarz (fragment, autor, data, treść) i jego
odpowiedzi. Panel tylko prezentuje i zgłasza żądania — decyzje podejmuje
``ui/comments_controller.py``. Pozycję wskazuje para (komentarz, odpowiedź),
gdzie odpowiedź None oznacza sam komentarz.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.comments import Comment, display_date
from transkryptor.i18n import tr
from transkryptor.ui.compare_panel import short
from transkryptor.ui.theme import set_props, tokens

# Rola danych elementu drzewa: (indeks komentarza, indeks odpowiedzi | None).
_ROLE = Qt.ItemDataRole.UserRole


class CommentsPanel(QWidget):
    """Lista komentarzy z wątkami i przyciskami działań."""

    add_requested = Signal()
    activated = Signal(int)
    reply_requested = Signal(int)
    edit_requested = Signal(int, object)  # komentarz, odpowiedź | None
    remove_requested = Signal(int, object)
    play_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("comments_panel")
        self.tree = QTreeWidget()
        self.tree.setObjectName("comments_tree")
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        set_props(self.tree, flat=True)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.itemClicked.connect(self._on_activated)
        self.tree.currentItemChanged.connect(lambda *_args: self._update_buttons())

        self.add_button = QPushButton(tr("comments.add"))
        self.reply_button = QPushButton(tr("comments.reply"))
        self.edit_button = QPushButton(tr("comments.edit"))
        self.remove_button = QPushButton(tr("comments.remove"))
        self.play_button = QPushButton(tr("comments.play"))
        set_props(self.add_button, variant="primary")
        self.add_button.clicked.connect(self.add_requested)
        self.reply_button.clicked.connect(
            lambda: self._emit(lambda c, _r: self.reply_requested.emit(c))
        )
        self.edit_button.clicked.connect(
            lambda: self._emit(lambda c, r: self.edit_requested.emit(c, r))
        )
        self.remove_button.clicked.connect(
            lambda: self._emit(lambda c, r: self.remove_requested.emit(c, r))
        )
        self.play_button.clicked.connect(
            lambda: self._emit(lambda c, _r: self.play_requested.emit(c))
        )

        buttons = QGridLayout()
        buttons.addWidget(self.add_button, 0, 0)
        buttons.addWidget(self.reply_button, 0, 1)
        buttons.addWidget(self.play_button, 0, 2)
        buttons.addWidget(self.edit_button, 1, 0)
        buttons.addWidget(self.remove_button, 1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.tree, stretch=1)
        layout.addLayout(buttons)
        self._update_buttons()

    def set_comments(self, comments: list[Comment]) -> None:
        """Zastępuje drzewo komentarzami (z bieżącymi cytatami fragmentów)."""
        selected = self.selection()
        self.tree.clear()
        t = tokens()
        for index, comment in enumerate(comments):
            quote = (
                tr("comments.quote", quote=short(comment.quote))
                if not comment.is_point
                else tr("comments.quote.removed", quote=short(comment.quote))
            )
            top = QTreeWidgetItem(
                [
                    tr(
                        "comments.item",
                        quote=quote,
                        author=comment.author or tr("comments.anonymous"),
                        date=display_date(comment.created),
                        text=comment.text,
                    )
                ]
            )
            top.setData(0, _ROLE, (index, None))
            top.setToolTip(0, tr("comments.item.tooltip"))
            if comment.is_point:
                top.setForeground(0, QColor(t.text_muted))
            for number, reply in enumerate(comment.replies):
                child = QTreeWidgetItem(
                    [
                        tr(
                            "comments.reply_item",
                            author=reply.author or tr("comments.anonymous"),
                            date=display_date(reply.created),
                            text=reply.text,
                        )
                    ]
                )
                child.setData(0, _ROLE, (index, number))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        if selected is not None:
            self.select(*selected)
        self._update_buttons()

    def selection(self) -> tuple[int, int | None] | None:
        item = self.tree.currentItem()
        return None if item is None else item.data(0, _ROLE)

    def select(self, comment: int, reply: int | None = None) -> None:
        if not 0 <= comment < self.tree.topLevelItemCount():
            return
        item = self.tree.topLevelItem(comment)
        if item is None:
            return
        if reply is not None and 0 <= reply < item.childCount():
            item = item.child(reply) or item
        self.tree.setCurrentItem(item)

    def _emit(self, emit) -> None:
        selected = self.selection()
        if selected is not None:
            emit(*selected)

    def _on_activated(self, item: QTreeWidgetItem) -> None:
        comment, _reply = item.data(0, _ROLE)
        self.activated.emit(comment)

    def _update_buttons(self) -> None:
        selected = self.selection() is not None
        for button in (
            self.reply_button,
            self.edit_button,
            self.remove_button,
            self.play_button,
        ):
            button.setEnabled(selected)
