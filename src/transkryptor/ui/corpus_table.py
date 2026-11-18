"""Tabele okna „Korpus”: konkordancja trafień i proste tabele wyników."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from transkryptor.corpus.concordance import Hit
from transkryptor.i18n import tr
from transkryptor.ui.player_bar import format_ms


class HitTable(QTableWidget):
    """Konkordancja: projekt, mówca, kontekst, trafienie, kontekst, czas."""

    PROJECT, SPEAKER, LEFT, MATCH, RIGHT, TIME = range(6)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(
            [
                tr("corpus.hits.project"),
                tr("corpus.hits.speaker"),
                tr("corpus.hits.left"),
                tr("corpus.hits.match"),
                tr("corpus.hits.right"),
                tr("corpus.hits.time"),
            ]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        for column in (self.PROJECT, self.SPEAKER, self.MATCH, self.TIME):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (self.LEFT, self.RIGHT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self._hits: list[Hit] = []

    @property
    def hits(self) -> list[Hit]:
        return list(self._hits)

    def set_hits(self, hits: Sequence[Hit], folder: Path | None) -> None:
        self._hits = list(hits)
        self.setUpdatesEnabled(False)
        self.clearContents()
        self.setRowCount(len(self._hits))
        bold = QFont(self.font())
        bold.setBold(True)
        for row, hit in enumerate(self._hits):
            project = QTableWidgetItem(hit.project.relative_name(folder))
            if hit.project.path is not None:
                project.setToolTip(str(hit.project.path))
            left = QTableWidgetItem(hit.left)
            left.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            match = QTableWidgetItem(hit.match)
            match.setFont(bold)
            time = QTableWidgetItem(
                "" if hit.time_ms is None else format_ms(hit.time_ms[0])
            )
            for column, item in (
                (self.PROJECT, project),
                (self.SPEAKER, QTableWidgetItem(hit.speaker)),
                (self.LEFT, left),
                (self.MATCH, match),
                (self.RIGHT, QTableWidgetItem(hit.right)),
                (self.TIME, time),
            ):
                self.setItem(row, column, item)
        self.setUpdatesEnabled(True)
        if self._hits:
            self.selectRow(0)

    def current_hit(self) -> Hit | None:
        row = self.currentRow()
        if 0 <= row < len(self._hits):
            return self._hits[row]
        return None


def table_widget(columns: Sequence[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    return table


def count_item(value: str | int) -> QTableWidgetItem:
    item = QTableWidgetItem()
    # Liczby jako liczby - sortowanie kolumny po wartości, nie po tekście.
    item.setData(Qt.ItemDataRole.DisplayRole, value)
    return item


__all__ = ["HitTable", "count_item", "table_widget"]
