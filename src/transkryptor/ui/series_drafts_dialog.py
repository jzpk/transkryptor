"""Okno startu kolejki szkiców ASR dla serii: co czeka i wspólne ustawienia.

Model i liczbę mówców wybiera się raz dla całej kolejki (język szkicu to
zawsze polski). Okno podaje, ile nagrań czeka na szkic i jak długo trwają,
a ile ma już szkic albo zostanie pominiętych.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from transkryptor.asr.diarization import MAX_SPEAKERS
from transkryptor.asr.models import AsrModelInfo
from transkryptor.document.progress import format_duration
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props


class SeriesDraftsDialog(QDialog):
    """Model i liczba mówców dla kolejki; ``summary`` - opis kolejki.

    ``speakers`` None - podział na mówców nie zadziała (bez modelu albo
    wyłączony), więc liczby mówców nie da się wybrać.
    """

    def __init__(
        self,
        models: Sequence[AsrModelInfo],
        model_key: str,
        speakers: int | None,
        summary: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("series_drafts_dialog")
        self.setWindowTitle(tr("series.drafts.dialog"))
        self.model_combo = QComboBox()
        for model in models:
            self.model_combo.addItem(model.display_name, model.key)
        self.model_combo.setCurrentIndex(max(self.model_combo.findData(model_key), 0))
        self.speakers_combo = QComboBox()
        self.speakers_combo.addItem(tr("settings.asr.diarize.speakers.auto"), 0)
        for count in range(2, MAX_SPEAKERS + 1):
            self.speakers_combo.addItem(str(count), count)
        if speakers is None:
            self.speakers_combo.setEnabled(False)
            self.speakers_combo.setToolTip(tr("series.drafts.no_diarization"))
        else:
            self.speakers_combo.setCurrentIndex(
                max(self.speakers_combo.findData(speakers), 0)
            )
        self._build_layout(summary)

    def _build_layout(self, summary: str) -> None:
        summary_label = QLabel(summary)
        summary_label.setObjectName("series_drafts_summary")
        summary_label.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("series.drafts.model"), self.model_combo)
        form.addRow(tr("settings.asr.diarize.speakers"), self.speakers_combo)
        form.addRow(tr("series.drafts.language"), QLabel(tr("series.drafts.polish")))
        note = QLabel(tr("series.drafts.note"))
        note.setWordWrap(True)
        set_props(note, role="muted")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText(tr("series.drafts.start"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(summary_label)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.setMinimumWidth(460)

    @property
    def model_key(self) -> str:
        return str(self.model_combo.currentData())

    @property
    def speakers(self) -> int:
        return int(self.speakers_combo.currentData())


def queue_summary(pending: int, duration_ms: int, drafted: int, skipped: int) -> str:
    """Opis kolejki: czekające (z łącznym czasem), gotowe i pominięte."""
    return tr(
        "series.drafts.summary",
        pending=pending,
        duration=format_duration(duration_ms // 1000) if duration_ms else "-",
        drafted=drafted,
        skipped=skipped,
    )


__all__ = ["SeriesDraftsDialog", "queue_summary"]
