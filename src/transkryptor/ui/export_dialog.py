"""Okno „Eksportuj jako…”: format z rejestru i opcje formatu (propozycja 18).

Formaty z czasami (ELAN, Praat, napisy) są niedostępne, gdy tekst nie ma
kotwic czasowych. Opcje pokazują się tylko dla formatów, których dotyczą.
DOCX, ODT i PDF mogą podświetlić wybrane części mowy (zgłoszenie #54) -
na starcie zaznaczone są te, które podświetla edytor.
"""

from __future__ import annotations

from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.parts_of_speech import PartOfSpeech
from transkryptor.export.options import UNTIMED_MODES, ExportOptions
from transkryptor.export.registry import (
    EXPORTERS,
    OPTION_PARTS_OF_SPEECH,
    OPTION_SUPERSCRIPT,
    OPTION_UNTIMED,
    Exporter,
    exporter_by_key,
)
from transkryptor.export.superscript import MODES
from transkryptor.i18n import tr
from transkryptor.ui.phrase_highlights import swatch
from transkryptor.ui.pos_highlights import pos_color
from transkryptor.ui.theme import set_props

POS_COLUMNS = 2


class ExportDialog(QDialog):
    """Format i opcje; ``initial`` - opcje zaznaczone na starcie.

    ``pos_available`` - czy analizator części mowy działa (bez niego grupa
    podświetleń jest wyłączona).
    """

    def __init__(
        self,
        format_key: str = "docx",
        initial: ExportOptions | None = None,
        has_times: bool = True,
        pos_available: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("export_dialog.title"))
        initial = initial or ExportOptions()
        self._build_format_combo(format_key, has_times)
        self._build_option_combos(initial)
        self._build_parts_of_speech(initial.parts_of_speech, pos_available)
        self._build_layout(has_times)
        self.format_combo.currentIndexChanged.connect(self._update)
        self._update()

    def _build_format_combo(self, format_key: str, has_times: bool) -> None:
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

    def _build_option_combos(self, initial: ExportOptions) -> None:
        self.superscript_combo = QComboBox()
        for mode in MODES:
            self.superscript_combo.addItem(tr(f"export.superscript.{mode}"), mode)
        self.superscript_combo.setCurrentIndex(
            max(self.superscript_combo.findData(initial.superscript), 0)
        )
        self.untimed_combo = QComboBox()
        for mode in UNTIMED_MODES:
            self.untimed_combo.addItem(tr(f"export.untimed.{mode}"), mode)
        self.untimed_combo.setCurrentIndex(
            max(self.untimed_combo.findData(initial.untimed), 0)
        )
        self.anonymize_check = QCheckBox(tr("export_dialog.anonymize"))
        self.anonymize_check.setToolTip(tr("toolbar.export_anonymized.tooltip"))

    def _build_parts_of_speech(
        self, selected: tuple[PartOfSpeech, ...], available: bool
    ) -> None:
        """Pola wyboru części mowy podświetlanych w pliku."""
        self.pos_group = QGroupBox(tr("export_dialog.pos"))
        self.pos_group.setObjectName("export_pos_group")
        self.pos_group.setToolTip(
            tr("export_dialog.pos.tooltip")
            if available
            else tr("highlights.pos.unavailable")
        )
        self.pos_group.setEnabled(available)
        grid = QGridLayout(self.pos_group)
        self.pos_checks: dict[PartOfSpeech, QCheckBox] = {}
        for index, part in enumerate(PartOfSpeech):
            check = QCheckBox(tr(f"pos.{part}"))
            check.setIcon(swatch(pos_color(part)))
            check.setChecked(available and part in selected)
            grid.addWidget(check, index // POS_COLUMNS, index % POS_COLUMNS)
            self.pos_checks[part] = check

    def _build_layout(self, has_times: bool) -> None:
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
        layout.addWidget(self.pos_group)
        layout.addWidget(self.description)
        layout.addWidget(self.times_hint)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)

    @property
    def exporter(self) -> Exporter:
        return exporter_by_key(self.format_combo.currentData())

    def options(self) -> ExportOptions:
        return ExportOptions(
            superscript=self.superscript_combo.currentData(),
            untimed=self.untimed_combo.currentData(),
            parts_of_speech=self.parts_of_speech,
        )

    @property
    def parts_of_speech(self) -> tuple[PartOfSpeech, ...]:
        """Zaznaczone części mowy (puste dla formatów bez podświetleń)."""
        if OPTION_PARTS_OF_SPEECH not in self.exporter.options:
            return ()
        return tuple(
            part for part, check in self.pos_checks.items() if check.isChecked()
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
        self.pos_group.setVisible(OPTION_PARTS_OF_SPEECH in exporter.options)
        self.description.setText(tr(f"export.format.{exporter.key}.description"))
        self.adjustSize()
