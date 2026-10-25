"""Panel listy zmian porównania wersji (faza 14, REQ-27).

Lista pokazuje zmiany z ``document/diff.py`` (typ, fragment przed i po,
stan: oczekuje, przyjęta, odrzucona); wybranie pozycji zaznacza fragment
w obu kolumnach. Przyciski przyjmują i odrzucają zmiany, cofają operacje
i kończą porównanie - decyzje podejmuje ``ui/compare_controller.py``.
"""

from __future__ import annotations

from PySide6.QtCore import Signal, SignalInstance
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.diff import DELETE, FORMAT, INSERT, REPLACE, SPEAKER
from transkryptor.i18n import tr
from transkryptor.ui import icons
from transkryptor.ui.theme import set_props, tokens

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"

# Fragment na liście: najwyżej tyle znaków, nowa linia jako ¶.
LABEL_MAX_CHARS = 40


def short(text: str) -> str:
    """Fragment do etykiety listy (widoczne granice akapitów, skrócony)."""
    text = text.replace("\n", "¶")
    if len(text) > LABEL_MAX_CHARS:
        text = text[: LABEL_MAX_CHARS - 1] + "…"
    return text


def change_label(kind: str, before: str, after: str) -> str:
    """Opis zmiany: typ i fragment przed/po (dla mówcy - klucze)."""
    if kind == INSERT:
        return tr("compare.item.insert", after=short(after))
    if kind == DELETE:
        return tr("compare.item.delete", before=short(before))
    if kind == REPLACE:
        return tr("compare.item.replace", before=short(before), after=short(after))
    if kind == FORMAT:
        return tr("compare.item.format", before=short(before))
    if kind == SPEAKER:
        return tr(
            "compare.item.speaker",
            before=before or tr("compare.no_speaker"),
            after=after or tr("compare.no_speaker"),
        )
    raise ValueError(f"Nieznany typ zmiany: {kind}")


class ComparePanel(QWidget):
    """Lista zmian z przyciskami decyzji."""

    item_activated = Signal(int)
    accept_requested = Signal(int)
    reject_requested = Signal(int)
    play_requested = Signal(int)
    accept_all_requested = Signal()
    reject_all_requested = Signal()
    finish_requested = Signal()

    def __init__(self, undo_action: QAction, redo_action: QAction, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("compare_panel")
        self.title = QLabel()
        self.title.setWordWrap(True)
        set_props(self.title, role="muted")
        self.list = QListWidget()
        self.list.setObjectName("compare_list")
        set_props(self.list, flat=True)
        self.list.setIconSize(icons.ICON_SIZE)
        self.list.itemActivated.connect(self._on_activated)
        self.list.itemClicked.connect(self._on_activated)
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())

        self.accept_button = QPushButton(tr("compare.accept"))
        self.reject_button = QPushButton(tr("compare.reject"))
        self.play_button = QPushButton(tr("compare.play"))
        self.accept_all_button = QPushButton(tr("compare.accept_all"))
        self.reject_all_button = QPushButton(tr("compare.reject_all"))
        self.finish_button = QPushButton(tr("compare.finish"))
        set_props(self.accept_button, variant="primary")
        self.accept_button.clicked.connect(
            lambda: self._emit_current(self.accept_requested)
        )
        self.reject_button.clicked.connect(
            lambda: self._emit_current(self.reject_requested)
        )
        self.play_button.clicked.connect(
            lambda: self._emit_current(self.play_requested)
        )
        self.accept_all_button.clicked.connect(self.accept_all_requested)
        self.reject_all_button.clicked.connect(self.reject_all_requested)
        self.finish_button.clicked.connect(self.finish_requested)
        self.undo_button = QToolButton()
        self.undo_button.setDefaultAction(undo_action)
        self.redo_button = QToolButton()
        self.redo_button.setDefaultAction(redo_action)

        buttons = QGridLayout()
        buttons.addWidget(self.accept_button, 0, 0)
        buttons.addWidget(self.reject_button, 0, 1)
        buttons.addWidget(self.play_button, 0, 2)
        buttons.addWidget(self.accept_all_button, 1, 0)
        buttons.addWidget(self.reject_all_button, 1, 1)
        buttons.addWidget(self.finish_button, 1, 2)
        buttons.addWidget(self.undo_button, 2, 0)
        buttons.addWidget(self.redo_button, 2, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.title)
        layout.addWidget(self.list, stretch=1)
        layout.addLayout(buttons)
        self._states: list[str] = []
        self._update_buttons()

    def set_title(self, name: str) -> None:
        self.title.setText(tr("compare.title", name=name))

    def set_items(self, items: list[tuple[str, str]]) -> None:
        """Zastępuje listę parami (opis, stan), zachowując bieżącą pozycję."""
        row = self.list.currentRow()
        self._states = [state for _label, state in items]
        self.list.clear()
        t = tokens()
        for label, state in items:
            if state == ACCEPTED:
                icon = icons.icon("check_circle", t.success)
                text = tr("compare.state.accepted", label=label)
            elif state == REJECTED:
                icon = icons.icon("close", t.text_muted)
                text = tr("compare.state.rejected", label=label)
            else:
                icon = icons.icon("compare", t.accent)
                text = label
            item = QListWidgetItem(icon, text)
            if state != PENDING:
                item.setForeground(QColor(t.text_muted))
            item.setToolTip(tr("compare.item.tooltip"))
            self.list.addItem(item)
        if items:
            self.list.setCurrentRow(min(max(row, 0), len(items) - 1))
        self._update_buttons()

    def current_index(self) -> int:
        return self.list.currentRow()

    def select(self, index: int) -> None:
        self.list.setCurrentRow(index)

    def _emit_current(self, signal: SignalInstance) -> None:
        index = self.list.currentRow()
        if 0 <= index < len(self._states):
            signal.emit(index)

    def _on_activated(self, item: QListWidgetItem) -> None:
        index = self.list.row(item)
        if 0 <= index < len(self._states):
            self.item_activated.emit(index)

    def _update_buttons(self) -> None:
        index = self.list.currentRow()
        state = self._states[index] if 0 <= index < len(self._states) else None
        self.accept_button.setEnabled(state == PENDING)
        self.reject_button.setEnabled(state == PENDING)
        self.play_button.setEnabled(state is not None)
        pending = PENDING in self._states
        self.accept_all_button.setEnabled(pending)
        self.reject_all_button.setEnabled(pending)
