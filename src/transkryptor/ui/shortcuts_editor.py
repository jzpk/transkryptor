"""Zakładki „Skróty” i „Wstawki” okna ustawień (propozycja 21).

Skróty edytuje się w ``QKeySequenceEdit`` (skrót główny i zapasowy dla
każdej akcji z ``SHORTCUT_ACTIONS``); wstawki to tabela tekstu w składni
``^x`` i opcjonalnego skrótu. Wykrywanie konfliktów obejmuje obie zakładki
— robi to okno ustawień przed zapisem.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.settings import Snippet
from transkryptor.ui.shortcuts import (
    SHORTCUT_ACTIONS,
    effective_shortcuts,
    normalized,
)
from transkryptor.ui.snippets import (
    SUGGESTED_SNIPPET_SHORTCUTS,
    parse_snippet,
    snippet_id,
    snippet_label,
)
from transkryptor.ui.theme import set_props

SEQUENCE_COLUMNS = (1, 2)  # skrót główny i zapasowy
KEY_COLUMN_WIDTH = 180  # mieści „Ctrl+Shift+Space” z przyciskiem czyszczenia


def key_edit(sequence: str = "") -> QKeySequenceEdit:
    """Pole jednego skrótu (jeden akord) z przyciskiem czyszczenia."""
    edit = QKeySequenceEdit(QKeySequence(sequence))
    edit.setMaximumSequenceLength(1)
    edit.setClearButtonEnabled(True)
    return edit


def edit_text(edit: QKeySequenceEdit) -> str:
    return edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)


class ShortcutsEditor(QWidget):
    """Tabela akcji ze skrótem głównym i zapasowym."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        hint = QLabel(tr("settings.shortcuts.hint"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.table = QTableWidget(len(SHORTCUT_ACTIONS), 3)
        self.table.setHorizontalHeaderLabels(
            [
                tr("settings.shortcuts.action"),
                tr("settings.shortcuts.primary"),
                tr("settings.shortcuts.alternative"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in SEQUENCE_COLUMNS:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, KEY_COLUMN_WIDTH)
        self.edits: dict[str, tuple[QKeySequenceEdit, QKeySequenceEdit]] = {}
        for row, definition in enumerate(SHORTCUT_ACTIONS):
            item = QTableWidgetItem(definition.label)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setData(Qt.ItemDataRole.UserRole, definition.id)
            self.table.setItem(row, 0, item)
            primary, alternative = key_edit(), key_edit()
            for column, edit in zip(
                SEQUENCE_COLUMNS, (primary, alternative), strict=True
            ):
                edit.keySequenceChanged.connect(lambda _seq: self.changed.emit())
                self.table.setCellWidget(row, column, edit)
            self.edits[definition.id] = (primary, alternative)
        self.table.resizeRowsToContents()

        self.conflicts_label = QLabel()
        self.conflicts_label.setWordWrap(True)
        set_props(self.conflicts_label, tone="warning")
        self.reset_row_button = QPushButton(tr("settings.shortcuts.reset_row"))
        self.reset_all_button = QPushButton(tr("settings.shortcuts.reset_all"))
        self.reset_row_button.clicked.connect(self.reset_current_row)
        self.reset_all_button.clicked.connect(lambda: self.set_overrides({}))
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_row_button)
        buttons.addWidget(self.reset_all_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(hint)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(buttons)
        layout.addWidget(self.conflicts_label)

    def set_overrides(self, overrides: Mapping[str, Iterable[str]]) -> None:
        for action_id, sequences in effective_shortcuts(overrides).items():
            self.set_shortcuts(action_id, sequences)

    def set_shortcuts(self, action_id: str, sequences: Iterable[str]) -> None:
        values = list(sequences)[:2]
        values += [""] * (2 - len(values))
        for edit, value in zip(self.edits[action_id], values, strict=True):
            edit.setKeySequence(QKeySequence(value))

    def reset_current_row(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(SHORTCUT_ACTIONS):
            definition = SHORTCUT_ACTIONS[row]
            self.set_shortcuts(definition.id, definition.defaults)

    def mapping(self) -> dict[str, tuple[str, ...]]:
        """Identyfikator akcji → skróty (bez pustych i powtórzeń)."""
        result: dict[str, tuple[str, ...]] = {}
        for action_id, edits in self.edits.items():
            sequences: list[str] = []
            for edit in edits:
                text = normalized(edit_text(edit))
                if text and text not in sequences:
                    sequences.append(text)
            result[action_id] = tuple(sequences)
        return result


class SnippetsEditor(QWidget):
    """Lista wstawek: tekst w składni ``^x``, skrót i podgląd."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        hint = QLabel(tr("settings.snippets.hint"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [
                tr("settings.snippets.text"),
                tr("settings.snippets.shortcut"),
                tr("settings.snippets.preview"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, KEY_COLUMN_WIDTH)
        self.table.itemChanged.connect(self._on_item_changed)
        self.add_button = QPushButton(tr("settings.snippets.add"))
        self.remove_button = QPushButton(tr("settings.snippets.remove"))
        self.add_button.clicked.connect(lambda: self.add_snippet())
        self.remove_button.clicked.connect(self.remove_current)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        set_props(self.problem_label, tone="warning")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(hint)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(buttons)
        layout.addWidget(self.problem_label)
        self._taken: set[str] = set()

    def set_taken_shortcuts(self, taken: Iterable[str]) -> None:
        """Skróty akcji — nowa wstawka nie dostaje zajętego skrótu."""
        self._taken = {normalized(s) for s in taken}

    def set_snippets(self, snippets: Iterable[Snippet]) -> None:
        self.table.setRowCount(0)
        for snippet in snippets:
            self.add_snippet(snippet.text, snippet.shortcut)
        self.changed.emit()

    def add_snippet(self, text: str = "", shortcut: str | None = None) -> int:
        """Dodaje wiersz; bez skrótu dostaje pierwszy wolny ``Alt+1…9``."""
        if shortcut is None:
            used = self._taken | {normalized(s.shortcut) for s in self.snippets(True)}
            shortcut = next(
                (s for s in SUGGESTED_SNIPPET_SHORTCUTS if normalized(s) not in used),
                "",
            )
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(text))
        preview = QTableWidgetItem()
        preview.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(row, 2, preview)
        self.table.blockSignals(False)
        edit = key_edit(shortcut)
        edit.keySequenceChanged.connect(lambda _seq: self.changed.emit())
        self.table.setCellWidget(row, 1, edit)
        self._update_preview(row)
        self.table.setCurrentCell(row, 0)
        self.changed.emit()
        return row

    def set_text(self, row: int, text: str) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            item.setText(text)

    def remove_current(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.changed.emit()

    def snippets(self, keep_empty: bool = False) -> tuple[Snippet, ...]:
        result: list[Snippet] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            text = item.text().strip() if item is not None else ""
            edit = self.table.cellWidget(row, 1)
            shortcut = (
                normalized(edit_text(edit))
                if isinstance(edit, QKeySequenceEdit)
                else ""
            )
            if text or keep_empty:
                result.append(Snippet(text, shortcut))
        return tuple(result)

    def shortcut_mapping(self) -> dict[str, tuple[str, ...]]:
        return {
            snippet_id(index): (snippet.shortcut,)
            for index, snippet in enumerate(self.snippets())
            if snippet.shortcut
        }

    def first_problem(self) -> str | None:
        for snippet in self.snippets():
            if parse_snippet(snippet.text) is None:
                return tr("settings.snippets.invalid", text=snippet.text)
        return None

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._update_preview(item.row())
            self.changed.emit()

    def _update_preview(self, row: int) -> None:
        text_item = self.table.item(row, 0)
        preview = self.table.item(row, 2)
        if text_item is None or preview is None:
            return
        parsed = parse_snippet(text_item.text().strip())
        self.table.blockSignals(True)
        preview.setText(
            snippet_label(parsed) if parsed is not None else tr("settings.snippets.bad")
        )
        self.table.blockSignals(False)
        problem = self.first_problem()
        self.problem_label.setText(problem or "")
