"""Rozmówcy w kroku „Szkic” panelu ASR: lista mówców i liczba głosów.

Przed transkrypcją badacz widzi, kim są rozmówcy nagrania (legenda listy
mówców dokumentu, np. ``B - Badacz; I - Informator``), może ją poprawić
przyciskiem „Mówcy…” i wybrać, ilu mówców ma rozpoznać podział na mówców
(zgł. #56). Wiersz jest widoczny zawsze: gdy liczby nie da się użyć
(podział wyłączony, brak modelu albo układ „pytanie - odpowiedź”), pole
jest wyłączone, a podpis mówi dlaczego.

Pole nie zmienia dokumentu ani ustawień samo: wybór liczby ogłasza
sygnałem ``count_changed``, a prośbę o edycję listy - ``edit_requested``.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from transkryptor.asr.diarization import MAX_SPEAKERS
from transkryptor.i18n import tr
from transkryptor.ui.asr_widgets import AutoHideLabel
from transkryptor.ui.theme import set_props

# Dlaczego liczba mówców nie jest używana (klucz podpisu pod polem).
COUNT_ACTIVE = ""
COUNT_DIARIZE_OFF = "asr.speakers.count.off"
COUNT_NO_MODEL = "asr.speakers.count.no_model"
COUNT_QA_LAYOUT = "asr.speakers.count.qa"


class SpeakersBox(QWidget):
    """Legenda mówców z przyciskiem edycji i wybór liczby mówców."""

    count_changed = Signal(int)  # liczba wybrana przez użytkownika; 0 - auto
    edit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("asr_speakers_box")
        self.legend_label = QLabel(tr("metadata_form.speakers.none"))
        self.legend_label.setObjectName("asr_speakers_legend")
        self.legend_label.setWordWrap(True)
        self.edit_button = QPushButton(tr("metadata_form.speakers.edit"))
        self.edit_button.setObjectName("asr_speakers_button")
        self.edit_button.setToolTip(tr("metadata_form.speakers.tooltip"))
        self.count_combo = QComboBox()
        self.count_combo.setObjectName("asr_speakers_count")
        self.count_combo.addItem(tr("settings.asr.diarize.speakers.auto"), 0)
        for count in range(2, MAX_SPEAKERS + 1):
            self.count_combo.addItem(str(count), count)
        self.count_combo.setToolTip(tr("settings.asr.diarize.speakers.tooltip"))
        self.count_hint = AutoHideLabel()
        self.count_hint.setWordWrap(True)
        set_props(self.count_hint, role="muted")
        self._build_layout()
        self.edit_button.clicked.connect(self.edit_requested)
        self.count_combo.currentIndexChanged.connect(self._on_count_selected)

    def _build_layout(self) -> None:
        count_label = QLabel(tr("settings.asr.diarize.speakers"))
        count_label.setBuddy(self.count_combo)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)
        layout.addWidget(QLabel(tr("metadata_form.speakers")), 0, 0)
        layout.addWidget(self.legend_label, 0, 1)
        layout.addWidget(self.edit_button, 0, 2)
        layout.addWidget(count_label, 1, 0)
        layout.addWidget(self.count_combo, 1, 1, 1, 2)
        layout.addWidget(self.count_hint, 2, 0, 1, 3)
        layout.setColumnStretch(1, 1)

    def set_legend(self, text: str) -> None:
        """Legenda mówców dokumentu (``B - Badacz; I - Informator``)."""
        self.legend_label.setText(text or tr("metadata_form.speakers.none"))

    def count(self) -> int:
        """Wybrana liczba mówców; 0 - automatycznie."""
        return int(self.count_combo.currentData() or 0)

    def set_count(self, count: int) -> None:
        """Ustawia liczbę (np. z ustawień) bez emitowania ``count_changed``."""
        index = self.count_combo.findData(count)
        self.count_combo.blockSignals(True)
        self.count_combo.setCurrentIndex(max(index, 0))
        self.count_combo.blockSignals(False)

    def set_count_state(self, reason: str) -> None:
        """Czy liczba jest używana; ``reason`` to jeden z kluczy ``COUNT_*``."""
        self.count_combo.setEnabled(reason == COUNT_ACTIVE)
        self.count_hint.setText(tr(reason) if reason else "")

    def _on_count_selected(self, index: int) -> None:
        if index >= 0:
            self.count_changed.emit(self.count())
