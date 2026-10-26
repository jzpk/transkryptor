"""Panel komentarzy recenzji (faza 14, REQ-27).

Drzewo o jednym poziomie: komentarz (fragment, autor, data, treść) i jego
odpowiedzi. Panel tylko prezentuje i zgłasza żądania - decyzje podejmuje
``ui/comments_controller.py``. Pozycję wskazuje para (komentarz, odpowiedź),
gdzie odpowiedź None oznacza sam komentarz. Filtr nad listą pokazuje
wszystkie komentarze, tylko otwarte albo tylko rozwiązane; indeksy w parze
dotyczą zawsze pełnej listy komentarzy, nie widocznych pozycji.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
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

# Filtr listy komentarzy.
FILTER_ALL = "all"
FILTER_OPEN = "open"
FILTER_RESOLVED = "resolved"
FILTERS = (FILTER_ALL, FILTER_OPEN, FILTER_RESOLVED)


class CommentsPanel(QWidget):
    """Lista komentarzy z wątkami i przyciskami działań."""

    add_requested = Signal()
    activated = Signal(int)
    reply_requested = Signal(int)
    edit_requested = Signal(int, object)  # komentarz, odpowiedź | None
    remove_requested = Signal(int, object)
    play_requested = Signal(int)
    resolve_requested = Signal(int)

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
        self._comments: list[Comment] = []

        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("comments_filter")
        for key in FILTERS:
            self.filter_combo.addItem(tr(f"comments.filter.{key}"), key)
        self.filter_combo.setToolTip(tr("comments.filter.tooltip"))
        self.filter_combo.currentIndexChanged.connect(
            lambda _index: self.set_comments(self._comments)
        )
        self.count_label = QLabel()
        set_props(self.count_label, role="muted")
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_label = QLabel(tr("comments.filter"))
        filter_label.setBuddy(self.filter_combo)
        filter_row.addWidget(filter_label)
        filter_row.addWidget(self.filter_combo, stretch=1)
        filter_row.addWidget(self.count_label)

        self.add_button = QPushButton(tr("comments.add"))
        self.reply_button = QPushButton(tr("comments.reply"))
        self.edit_button = QPushButton(tr("comments.edit"))
        self.remove_button = QPushButton(tr("comments.remove"))
        self.play_button = QPushButton(tr("comments.play"))
        self.resolve_button = QPushButton(tr("comments.resolve"))
        self.resolve_button.setToolTip(tr("comments.resolve.tooltip"))
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
        self.resolve_button.clicked.connect(
            lambda: self._emit(lambda c, _r: self.resolve_requested.emit(c))
        )

        buttons = QGridLayout()
        buttons.addWidget(self.add_button, 0, 0)
        buttons.addWidget(self.reply_button, 0, 1)
        buttons.addWidget(self.play_button, 0, 2)
        buttons.addWidget(self.edit_button, 1, 0)
        buttons.addWidget(self.remove_button, 1, 1)
        buttons.addWidget(self.resolve_button, 1, 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(filter_row)
        layout.addWidget(self.tree, stretch=1)
        layout.addLayout(buttons)
        self._update_buttons()

    @property
    def filter(self) -> str:
        return self.filter_combo.currentData()

    def set_filter(self, key: str) -> None:
        self.filter_combo.setCurrentIndex(max(0, FILTERS.index(key)))

    def _shown(self, comment: Comment) -> bool:
        if self.filter == FILTER_OPEN:
            return not comment.resolved
        if self.filter == FILTER_RESOLVED:
            return comment.resolved
        return True

    def set_comments(self, comments: list[Comment]) -> None:
        """Zastępuje drzewo komentarzami (z bieżącymi cytatami fragmentów)."""
        selected = self.selection()
        self._comments = list(comments)
        self.tree.clear()
        t = tokens()
        open_count = sum(1 for comment in comments if not comment.resolved)
        self.count_label.setText(
            tr("comments.count", open=open_count, total=len(comments))
        )
        for index, comment in enumerate(comments):
            if not self._shown(comment):
                continue
            quote = (
                tr("comments.quote", quote=short(comment.quote))
                if not comment.is_point
                else tr("comments.quote.removed", quote=short(comment.quote))
            )
            text = tr(
                "comments.item",
                quote=quote,
                author=comment.author or tr("comments.anonymous"),
                date=display_date(comment.created),
                text=comment.text,
            )
            if comment.resolved:
                text = tr("comments.item.resolved", item=text)
            top = QTreeWidgetItem([text])
            top.setData(0, _ROLE, (index, None))
            top.setToolTip(0, tr("comments.item.tooltip"))
            if comment.is_point or comment.resolved:
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
        """Zaznacza komentarz (indeks pełnej listy); ukryty filtrem - pomija."""
        item = next(
            (
                top
                for top in map(
                    self.tree.topLevelItem, range(self.tree.topLevelItemCount())
                )
                if top is not None and top.data(0, _ROLE)[0] == comment
            ),
            None,
        )
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
        selection = self.selection()
        selected = selection is not None
        for button in (
            self.reply_button,
            self.edit_button,
            self.remove_button,
            self.play_button,
            self.resolve_button,
        ):
            button.setEnabled(selected)
        resolved = (
            selection is not None
            and selection[0] < len(self._comments)
            and self._comments[selection[0]].resolved
        )
        self.resolve_button.setText(
            tr("comments.reopen" if resolved else "comments.resolve")
        )
        self.resolve_button.setToolTip(
            tr("comments.reopen.tooltip" if resolved else "comments.resolve.tooltip")
        )
