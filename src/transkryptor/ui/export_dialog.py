"""Okno „Eksportuj jako…”: format z rejestru i opcje formatu (propozycja 18).

Formaty z czasami (ELAN, Praat, napisy) są niedostępne, gdy tekst nie ma
kotwic czasowych. Opcje pokazują się tylko dla formatów, których dotyczą.
"""

from __future__ import annotations

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from transkryptor.export.options import (
    UNTIMED_INTERPOLATE,
    UNTIMED_MODES,
    ExportOptions,
)
from transkryptor.export.registry import (
    EXPORTERS,
    OPTION_SUPERSCRIPT,
    OPTION_UNTIMED,
    Exporter,
    exporter_by_key,
)
from transkryptor.export.superscript import MODES, UNICODE
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props


class ExportDialog(QDialog):
    def __init__(
        self,
        format_key: str = "docx",
        superscript: str = UNICODE,
        untimed: str = UNTIMED_INTERPOLATE,
        has_times: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("export_dialog.title"))
        self.format_combo = QComboBox()
        for exporter in EXPORTERS:
            self.format_combo.addItem(exporter.label, exporter.key)
        model = self.format_combo.model()
        if not has_times and isinstance(model, QStandardItemModel):
            for row, exporter in enumerate(EXPORTERS):
                if exporter.timed:
                    item = model.item(row)
                    item.setEnabled(False)
                    item.setToolTip(tr("export_dialog.needs_times"))
        selected = exporter_by_key(format_key)
        if selected.timed and not has_times:
            selected = exporter_by_key("docx")
        self.format_combo.setCurrentIndex(self.format_combo.findData(selected.key))

        self.superscript_combo = QComboBox()
        for mode in MODES:
            self.superscript_combo.addItem(tr(f"export.superscript.{mode}"), mode)
        self.superscript_combo.setCurrentIndex(
            max(self.superscript_combo.findData(superscript), 0)
        )
        self.untimed_combo = QComboBox()
        for mode in UNTIMED_MODES:
            self.untimed_combo.addItem(tr(f"export.untimed.{mode}"), mode)
        self.untimed_combo.setCurrentIndex(max(self.untimed_combo.findData(untimed), 0))
        self.anonymize_check = QCheckBox(tr("export_dialog.anonymize"))
        self.anonymize_check.setToolTip(tr("toolbar.export_anonymized.tooltip"))

        self.description = QLabel()
        self.description.setWordWrap(True)
        set_props(self.description, role="muted")
        self.times_hint = QLabel(tr("export_dialog.no_times"))
        self.times_hint.setWordWrap(True)
        set_props(self.times_hint, role="muted")
        self.times_hint.setVisible(not has_times)

        form = QFormLayout()
        form.addRow(tr("export_dialog.format"), self.format_combo)
        form.addRow(tr("export_dialog.superscript"), self.superscript_combo)
        form.addRow(tr("export_dialog.untimed"), self.untimed_combo)
        form.addRow("", self.anonymize_check)
        self._form = form

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText(tr("export_dialog.ok"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.description)
        layout.addWidget(self.times_hint)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)

        self.format_combo.currentIndexChanged.connect(self._update)
        self._update()

    @property
    def exporter(self) -> Exporter:
        return exporter_by_key(self.format_combo.currentData())

    def options(self) -> ExportOptions:
        return ExportOptions(
            superscript=self.superscript_combo.currentData(),
            untimed=self.untimed_combo.currentData(),
        )

    @property
    def anonymize(self) -> bool:
        return self.anonymize_check.isChecked()

    def _update(self) -> None:
        exporter = self.exporter
        for widget, option in (
            (self.superscript_combo, OPTION_SUPERSCRIPT),
            (self.untimed_combo, OPTION_UNTIMED),
        ):
            self._form.setRowVisible(widget, option in exporter.options)
        self.description.setText(tr(f"export.format.{exporter.key}.description"))
        self.adjustSize()
