"""Okno listy mówców nagrania: klucz, etykieta i rola (faza 12).

Zwraca nową listę oraz zmiany kluczy (stary → nowy), żeby akapity
przypisane mówcy po zmianie klucza zostały przy nim. Usunięcie mówcy, który
ma akapity, wymaga potwierdzenia — te akapity tracą przypisanie.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.speakers import (
    KEY_MAX_LENGTH,
    OTHER,
    ROLES,
    Speaker,
    guess_role,
    is_valid_key,
    role_label,
)
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props

KEY_COLUMN, LABEL_COLUMN, ROLE_COLUMN = range(3)
ORIGINAL_KEY = Qt.ItemDataRole.UserRole


class SpeakersDialog(QDialog):
    def __init__(
        self,
        speakers: Iterable[Speaker],
        used_keys: Iterable[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("speakers.dialog.title"))
        speakers = list(speakers)
        self._initial = {speaker.key for speaker in speakers}
        self._used = set(used_keys)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [
                tr("speakers.dialog.key"),
                tr("speakers.dialog.label"),
                tr("speakers.dialog.role"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(KEY_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(LABEL_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            ROLE_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumWidth(420)

        hint = QLabel(tr("speakers.dialog.hint", length=KEY_MAX_LENGTH))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        set_props(self.error_label, role="status", tone="danger")
        self.error_label.hide()

        self.add_button = QPushButton(tr("speakers.dialog.add"))
        self.add_button.clicked.connect(self.add_speaker)
        self.remove_button = QPushButton(tr("speakers.dialog.remove"))
        self.remove_button.clicked.connect(self.remove_selected)
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self.add_button)
        buttons_row.addWidget(self.remove_button)
        buttons_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(buttons_row)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

        for speaker in speakers:
            self._append(speaker, original=speaker.key)

    def _append(self, speaker: Speaker, original: str | None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        key_item = QTableWidgetItem(speaker.key)
        key_item.setData(ORIGINAL_KEY, original)
        self.table.setItem(row, KEY_COLUMN, key_item)
        self.table.setItem(row, LABEL_COLUMN, QTableWidgetItem(speaker.label))
        combo = QComboBox()
        for role in ROLES:
            combo.addItem(role_label(role), role)
        combo.setCurrentIndex(max(combo.findData(speaker.role), 0))
        self.table.setCellWidget(row, ROLE_COLUMN, combo)

    def add_speaker(self) -> None:
        """Nowy wiersz z wolnym kluczem (``I2``, ``I3``… albo ``M1``…)."""
        keys = {speaker.key for speaker, _original in self._rows()}
        key = next(
            (f"I{n}" for n in range(2, 100) if f"I{n}" not in keys),
            "M",
        )
        self._append(Speaker(key, "", guess_role(key)), original=None)
        self.table.setCurrentCell(self.table.rowCount() - 1, KEY_COLUMN)

    def remove_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _rows(self) -> list[tuple[Speaker, str | None]]:
        rows: list[tuple[Speaker, str | None]] = []
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, KEY_COLUMN)
            label_item = self.table.item(row, LABEL_COLUMN)
            combo = self.table.cellWidget(row, ROLE_COLUMN)
            role = combo.currentData() if isinstance(combo, QComboBox) else OTHER
            key = key_item.text().strip() if key_item is not None else ""
            label = label_item.text().strip() if label_item is not None else ""
            original = key_item.data(ORIGINAL_KEY) if key_item is not None else None
            rows.append((Speaker(key, label, role), original))
        return rows

    def speakers(self) -> list[Speaker]:
        return [speaker for speaker, _original in self._rows()]

    def renamed(self) -> dict[str, str]:
        """Zmienione klucze istniejących mówców (stary → nowy)."""
        return {
            original: speaker.key
            for speaker, original in self._rows()
            if original is not None and original != speaker.key
        }

    def removed(self) -> set[str]:
        """Klucze mówców usuniętych z listy."""
        kept = {original for _speaker, original in self._rows() if original}
        return self._initial - kept

    def validation_error(self) -> str | None:
        keys: set[str] = set()
        for speaker in self.speakers():
            if not is_valid_key(speaker.key):
                return tr(
                    "speakers.dialog.invalid_key",
                    speaker=speaker.key,
                    length=KEY_MAX_LENGTH,
                )
            if speaker.key in keys:
                return tr("speakers.dialog.duplicate_key", speaker=speaker.key)
            keys.add(speaker.key)
        return None

    def accept(self) -> None:
        error = self.validation_error()
        if error is not None:
            self.error_label.setText(error)
            self.error_label.show()
            return
        lost = sorted(self.removed() & self._used)
        if lost:
            answer = QMessageBox.question(
                self,
                tr("speakers.dialog.title"),
                tr("speakers.dialog.remove_used", keys=", ".join(lost)),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().accept()
