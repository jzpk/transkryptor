"""Okno „Historia projektu”: lista migawek z porównaniem i przywróceniem.

Lista pokazuje migawki projektu od najnowszej (data, opis, liczba słów,
rodzaj: ręczna albo automatyczna). „Porównaj z bieżącym” i „Przywróć”
zamykają okno z wybraną migawką (``chosen``) i kodem akcji - wykonuje
ją ``SnapshotController``; „Usuń” usuwa migawkę od razu, po potwierdzeniu.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.snapshots import Snapshot, SnapshotStore
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props

_ROLE = Qt.ItemDataRole.UserRole

# Kody wyniku okna (obok Accepted/Rejected).
COMPARE = 2
RESTORE = 3


def snapshot_date(snapshot: Snapshot) -> str:
    return snapshot.created.strftime("%Y-%m-%d %H:%M:%S")


class HistoryDialog(QDialog):
    """Migawki jednego projektu."""

    def __init__(self, store: SnapshotStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("history_dialog")
        self.setWindowTitle(tr("snapshots.history.title"))
        self._store = store
        self.chosen: Snapshot | None = None

        header = QLabel(tr("snapshots.history.header"))
        set_props(header, role="title")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        set_props(self.hint, role="muted")

        self.tree = QTreeWidget()
        self.tree.setObjectName("history_tree")
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(
            [
                tr("snapshots.column.date"),
                tr("snapshots.column.label"),
                tr("snapshots.column.words"),
                tr("snapshots.column.kind"),
            ]
        )
        columns = self.tree.header()
        columns.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        columns.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemActivated.connect(lambda _item: self.choose(COMPARE))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.compare_button = buttons.addButton(
            tr("snapshots.compare"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.restore_button = buttons.addButton(
            tr("snapshots.restore"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.delete_button = buttons.addButton(
            tr("snapshots.delete"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.compare_button.clicked.connect(lambda: self.choose(COMPARE))
        self.restore_button.clicked.connect(lambda: self.choose(RESTORE))
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.hint)
        layout.addWidget(self.tree, stretch=1)
        layout.addWidget(buttons)
        self.resize(640, 420)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        snapshots = self._store.list()
        for snapshot in snapshots:
            item = QTreeWidgetItem(
                [
                    snapshot_date(snapshot),
                    snapshot.label,
                    str(snapshot.word_count),
                    tr(
                        "snapshots.kind.automatic"
                        if snapshot.automatic
                        else "snapshots.kind.manual"
                    ),
                ]
            )
            item.setData(0, _ROLE, snapshot)
            self.tree.addTopLevelItem(item)
        self.hint.setText(
            tr("snapshots.history.hint") if snapshots else tr("snapshots.history.empty")
        )
        if snapshots:
            self.select(0)
        self._update_buttons()

    def selected(self) -> Snapshot | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        snapshot = item.data(0, _ROLE)
        return snapshot if isinstance(snapshot, Snapshot) else None

    def select(self, index: int) -> None:
        item = self.tree.topLevelItem(index)
        if item is not None:
            self.tree.setCurrentItem(item)

    def delete_selected(self) -> None:
        snapshot = self.selected()
        if snapshot is None:
            return
        answer = QMessageBox.question(
            self,
            tr("snapshots.delete.title"),
            tr("snapshots.delete.text", date=snapshot_date(snapshot)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._store.delete(snapshot)
            self.refresh()

    def choose(self, action: int) -> None:
        """Zamyka okno z akcją ``COMPARE`` albo ``RESTORE`` dla zaznaczenia."""
        snapshot = self.selected()
        if snapshot is None:
            return
        self.chosen = snapshot
        self.done(action)

    def _update_buttons(self) -> None:
        enabled = self.selected() is not None
        for button in (self.compare_button, self.restore_button, self.delete_button):
            button.setEnabled(enabled)
