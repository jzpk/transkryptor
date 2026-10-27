"""Zwijany formularz metryczki nagrania w karcie transkrypcji.

Pola i ich kolejność pochodzą z ustawień („Metryczka”); formularz tylko
pokazuje wartości i zgłasza zmiany sygnałem ``changed``. Zapis do
``Document.metadata`` wykonuje ``SessionController``. Pod polami jest wiersz
listy mówców nagrania (faza 12) - edycję otwiera ``SpeakerController``
po sygnale ``speakers_edit_requested``. Blokadę na czas ASR
zapewnia wyłączenie karty transkrypcji (REQ-13).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.metadata import MetadataField, enabled_fields
from transkryptor.i18n import tr

# Pary etykieta-pole w dwóch kolumnach: rozwinięta metryczka nie zabiera
# edytorowi połowy wysokości karty.
COLUMNS = 2


class MetadataForm(QWidget):
    """Przycisk zwijania z podsumowaniem i formularz pól metryczki."""

    changed = Signal()
    speakers_edit_requested = Signal()

    def __init__(self, fields: Iterable[MetadataField], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metadata_form")
        self.toggle = QToolButton()
        self.toggle.setObjectName("metadata_toggle")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolTip(tr("metadata_form.tooltip"))
        self.toggle.toggled.connect(self._on_toggled)

        self.details = QWidget()
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(16, 4, 16, 8)
        details_layout.setSpacing(6)
        fields_widget = QWidget()
        self._grid = QGridLayout(fields_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        for column in range(COLUMNS):
            self._grid.setColumnStretch(column * 2 + 1, 1)
        details_layout.addWidget(fields_widget)

        self.speakers_label = QLabel()
        self.speakers_label.setWordWrap(True)
        self.speakers_button = QPushButton(tr("metadata_form.speakers.edit"))
        self.speakers_button.setToolTip(tr("metadata_form.speakers.tooltip"))
        self.speakers_button.clicked.connect(self.speakers_edit_requested)
        speakers_row = QHBoxLayout()
        speakers_row.setSpacing(8)
        speakers_row.addWidget(QLabel(tr("metadata_form.speakers")))
        speakers_row.addWidget(self.speakers_label, stretch=1)
        speakers_row.addWidget(self.speakers_button)
        details_layout.addLayout(speakers_row)
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
                edit.setToolTip(tr("metadata_form.personal_tooltip"))
            edit.textChanged.connect(self._on_edited)
            caption = QLabel(f"{metadata_field.display_label}:")
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

    def focus_field(self, key: str) -> bool:
        """Rozwija formularz i ustawia kursor w polu; False - pole ukryte."""
        edit = self.edits.get(key)
        if edit is None:
            return False
        self.toggle.setChecked(True)
        edit.setFocus()
        return True

    def set_speakers_summary(self, text: str) -> None:
        """Legenda mówców nagrania (``B - Badacz; I - Informator``)."""
        self.speakers_label.setText(text or tr("metadata_form.speakers.none"))

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
        self.toggle.setText(
            tr("metadata_form.toggle", filled=filled, total=len(self.edits))
        )


DATE_FORMAT = "yyyy-MM-dd"


@dataclass(frozen=True)
class MetadataWidgets:
    """Pola metryczki w oknie: autor, data i formularz pól zespołu."""

    author: QLineEdit
    date: QDateEdit
    form: MetadataForm

    def author_text(self) -> str:
        return self.author.text()

    def date_text(self) -> str:
        """Data w formacie ISO; pusta, gdy pole pokazuje datę minimalną."""
        date = self.date.date()
        return "" if date == self.date.minimumDate() else date.toString(DATE_FORMAT)

    def clear(self) -> None:
        """Nowy dokument: bez autora, z dzisiejszą datą i pustą metryczką."""
        self.author.clear()
        self.date.setDate(QDate.currentDate())
        self.form.set_values({})

    def restore(self, author: str, date: str, values: Mapping[str, str]) -> bool:
        """Wypełnia pola z projektu; zwraca, czy data była poprawna."""
        self.author.setText(author)
        parsed = QDate.fromString(date, DATE_FORMAT)
        self.date.setDate(parsed if parsed.isValid() else self.date.minimumDate())
        self.form.set_values(values)
        return parsed.isValid()
