"""Okno „Eksportuj serię…”: opcje „Eksportuj jako…” i wybór projektów serii.

Do formatu, opcji formatu i anonimizacji (``ui/export_dialog.py``) dochodzi
cel (katalog albo jedno archiwum ZIP) i „Tylko gotowe projekty”.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QWidget

from transkryptor.export.options import ExportOptions
from transkryptor.i18n import tr
from transkryptor.ui.export_dialog import ExportDialog

TARGET_FOLDER = "folder"
TARGET_ZIP = "zip"


class SeriesExportDialog(ExportDialog):
    """Format i opcje raz dla wszystkich projektów serii."""

    def __init__(
        self,
        format_key: str,
        initial: ExportOptions,
        pos_available: bool,
        count: int,
        parent: QWidget | None = None,
    ) -> None:
        # Projekty serii mają czasy albo nie - formaty z czasami pomijają te bez.
        super().__init__(format_key, initial, True, pos_available, parent)
        self.setObjectName("series_export_dialog")
        self.setWindowTitle(tr("series.export.dialog", count=count))
        self.target_combo = QComboBox()
        self.target_combo.addItem(tr("series.export.target.folder"), TARGET_FOLDER)
        self.target_combo.addItem(tr("series.export.target.zip"), TARGET_ZIP)
        self.ready_check = QCheckBox(tr("series.export.only_ready"))
        self.ready_check.setToolTip(tr("series.export.only_ready.tooltip"))
        self._form.addRow(tr("series.export.target"), self.target_combo)
        self._form.addRow("", self.ready_check)
        self.times_hint.setText(tr("series.export.times_hint"))
        self.times_hint.setVisible(True)

    @property
    def to_zip(self) -> bool:
        return self.target_combo.currentData() == TARGET_ZIP

    @property
    def only_ready(self) -> bool:
        return self.ready_check.isChecked()
