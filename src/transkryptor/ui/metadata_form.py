"""Zwijany formularz metryczki nagrania w karcie transkrypcji.

Pola i ich kolejność pochodzą z ustawień („Metryczka”); formularz tylko
pokazuje wartości i zgłasza zmiany sygnałem ``changed``. Zapis do
``Document.metadata`` wykonuje ``SessionController``. Blokadę na czas ASR
zapewnia wyłączenie karty transkrypcji (REQ-13).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.metadata import MetadataField, enabled_fields

TOGGLE_TEXT = "Metryczka nagrania"
# Pary etykieta–pole w dwóch kolumnach: rozwinięta metryczka nie zabiera
# edytorowi połowy wysokości karty.
COLUMNS = 2


class MetadataForm(QWidget):
    """Przycisk zwijania z podsumowaniem i formularz pól metryczki."""

    changed = Signal()

    def __init__(self, fields: Iterable[MetadataField], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metadata_form")
        self.toggle = QToolButton()
        self.toggle.setObjectName("metadata_toggle")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolTip(
            "Dane opisowe nagrania; trafiają do projektu i do tabeli w DOCX"
        )
        self.toggle.toggled.connect(self._on_toggled)

        self.details = QWidget()
        self._grid = QGridLayout(self.details)
        self._grid.setContentsMargins(16, 4, 16, 8)
        self._grid.setHorizontalSpacing(8)
        for column in range(COLUMNS):
            self._grid.setColumnStretch(column * 2 + 1, 1)
        self.details.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 4)
        layout.setSpacing(0)
        layout.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details)

        self.edits: dict[str, QLineEdit] = {}
        self._fields: tuple[MetadataField, ...] = ()
        self._hidden: dict[str, str] = {}
        self.set_fields(fields)

    def set_fields(self, fields: Iterable[MetadataField]) -> None:
        """Przebudowuje formularz; wartości pól zachowuje (także ukrytych)."""
        enabled = enabled_fields(fields)
        if enabled == self._fields:
            return
        values = self.values()
        while (item := self._grid.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.edits = {}
        self._fields = enabled
        for index, metadata_field in enumerate(self._fields):
            edit = QLineEdit()
            edit.setClearButtonEnabled(True)
            if metadata_field.personal:
                edit.setToolTip("Dane osobowe — pomijane w eksporcie anonimizowanym")
            edit.textChanged.connect(self._on_edited)
            caption = QLabel(f"{metadata_field.label}:")
            caption.setBuddy(edit)
            row, column = divmod(index, COLUMNS)
            self._grid.addWidget(caption, row, column * 2)
            self._grid.addWidget(edit, row, column * 2 + 1)
            self.edits[metadata_field.key] = edit
        self.set_values(values, emit=False)

    def values(self) -> dict[str, str]:
        """Wartości wszystkich pól (z polami ukrytymi w ustawieniach)."""
        result = dict(self._hidden)
        result.update({key: edit.text() for key, edit in self.edits.items()})
        return result

    def set_values(self, values: Mapping[str, str], emit: bool = False) -> None:
        self._hidden = {k: v for k, v in values.items() if k not in self.edits}
        for key, edit in self.edits.items():
            edit.blockSignals(True)
            edit.setText(values.get(key, ""))
            edit.blockSignals(False)
        self._update_summary()
        if emit:
            self.changed.emit()

    def set_value(self, key: str, value: str) -> None:
        """Ustawia jedno pole i zgłasza zmianę (np. podpowiedź sygnatury)."""
        edit = self.edits.get(key)
        if edit is not None:
            edit.setText(value)
        else:
            self._hidden[key] = value
            self._on_edited()

    def value(self, key: str) -> str:
        return self.values().get(key, "")

    def _on_edited(self) -> None:
        self._update_summary()
        self.changed.emit()

    def _on_toggled(self, expanded: bool) -> None:
        self.details.setVisible(expanded)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _update_summary(self) -> None:
        filled = sum(1 for edit in self.edits.values() if edit.text().strip())
        self.toggle.setText(f"{TOGGLE_TEXT} ({filled} z {len(self.edits)})")
