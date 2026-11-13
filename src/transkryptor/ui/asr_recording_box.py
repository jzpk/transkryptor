"""Dane nagrania w kroku „Szkic” panelu ASR: miejsce i informator.

Badacz wpisuje przed transkrypcją to, co i tak trafia do metryczki:
miejscowość, gminę/powiat, rok urodzenia i płeć informatora (zgł. #57).
Pola są widokiem tych samych wartości co formularz metryczki - pole nie
przechowuje własnego stanu: zmianę ogłasza sygnałem ``value_edited``,
a ``set_values`` odświeża je po każdej zmianie metryczki. Miejscowość
i gmina/powiat stają się też podpowiedzią kontekstu dla modelu
(``document.metadata.asr_context_hint``).
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QWidget

from transkryptor.document.metadata import (
    BIRTH_YEAR,
    DEFAULT_FIELDS,
    DISTRICT,
    GENDER,
    PLACE,
)
from transkryptor.i18n import tr

FIELD_KEYS = (PLACE, DISTRICT, BIRTH_YEAR, GENDER)


class RecordingFieldsBox(QWidget):
    """Pola metryczki potrzebne przed transkrypcją."""

    value_edited = Signal(str, str)  # klucz pola metryczki, nowa wartość

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("asr_recording_box")
        labels = {field.key: field.display_label for field in DEFAULT_FIELDS}
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        self.edits: dict[str, QLineEdit] = {}
        for row, key in enumerate(FIELD_KEYS):
            edit = QLineEdit()
            edit.setObjectName(f"asr_recording_{key}")
            edit.setClearButtonEnabled(True)
            edit.setToolTip(tr("asr.recording.tooltip"))
            edit.textEdited.connect(
                lambda text, key=key: self.value_edited.emit(key, text)
            )
            caption = QLabel(f"{labels[key]}:")
            caption.setWordWrap(True)  # wąski panel nie ucina pól (#57)
            caption.setBuddy(edit)
            layout.addWidget(caption, row, 0)
            layout.addWidget(edit, row, 1)
            self.edits[key] = edit

    def set_values(self, values: Mapping[str, str]) -> None:
        """Wartości z metryczki; pole w trakcie edycji nie traci kursora."""
        for key, edit in self.edits.items():
            value = values.get(key, "")
            if edit.text() != value:
                edit.setText(value)
