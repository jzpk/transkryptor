"""Zakładka „ASR” w ustawieniach: modele, urządzenie, mówcy, słownik, zapis szkicu."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from transkryptor.asr.manager import ModelManager
from transkryptor.asr.models import default_models_root
from transkryptor.i18n import tr
from transkryptor.settings import WORD_THRESHOLD_RANGE_PCT, Settings, split_vocabulary
from transkryptor.ui.asr_widgets import section_label
from transkryptor.ui.diarization_box import DiarizationBox
from transkryptor.ui.settings_pages import (
    FormPage,
    device_labels,
    hint_label,
    select_data,
)


class AsrPage(FormPage):
    """Katalog modeli, urządzenie, podział na mówców i słownik globalny."""

    def __init__(self, model_manager: ModelManager) -> None:
        super().__init__()
        self.models_root_edit = QLineEdit()
        self.models_root_edit.setReadOnly(True)
        self.models_root_edit.setPlaceholderText(str(default_models_root()))
        self.models_root_button = QPushButton(tr("settings.asr.models_root.choose"))
        self.models_root_button.clicked.connect(self._choose_models_root)
        self.models_root_default_button = QPushButton(
            tr("settings.asr.models_root.default")
        )
        self.models_root_default_button.clicked.connect(self.models_root_edit.clear)
        models_root_row = QHBoxLayout()
        models_root_row.addWidget(self.models_root_edit, stretch=1)
        models_root_row.addWidget(self.models_root_button)
        models_root_row.addWidget(self.models_root_default_button)
        self.device_combo = QComboBox()
        for device, device_label in device_labels().items():
            self.device_combo.addItem(device_label, device)
        self.chunked_check = QCheckBox(tr("settings.asr.chunked"))
        self.word_timestamps_check = QCheckBox(tr("settings.asr.word_timestamps"))
        self.word_timestamps_check.setToolTip(
            tr("settings.asr.word_timestamps.tooltip")
        )
        self.diarization_box = DiarizationBox(model_manager)
        self.models_root_edit.textChanged.connect(
            lambda text: self.diarization_box.set_models_root(models_root(text))
        )
        self.uncertain_words_check = QCheckBox(tr("settings.asr.uncertain_words"))
        self.word_threshold_spin = QSpinBox()
        self.word_threshold_spin.setRange(*WORD_THRESHOLD_RANGE_PCT)
        self.word_threshold_spin.setSuffix(" %")
        self.word_threshold_spin.setToolTip(tr("settings.asr.word_threshold.tooltip"))
        self.uncertain_words_check.toggled.connect(self.word_threshold_spin.setEnabled)
        self.vocabulary_edit = QPlainTextEdit()
        self.vocabulary_edit.setPlaceholderText(
            tr("settings.asr.vocabulary.placeholder")
        )
        self.vocabulary_edit.setTabChangesFocus(True)
        self.expand_abbreviations_check = QCheckBox(
            tr("settings.asr.expand_abbreviations")
        )
        self.lowercase_plain_check = QCheckBox(tr("settings.asr.lowercase_plain"))
        self.verbatim_check = QCheckBox(tr("settings.asr.verbatim"))
        self.form.addRow(tr("settings.asr.models_root"), models_root_row)
        self.form.addRow(hint_label(tr("settings.asr.models_root.hint")))
        self.form.addRow(tr("settings.asr.device"), self.device_combo)
        self.form.addRow(hint_label(tr("settings.asr.device.hint")))
        self.form.addRow(self.chunked_check)
        self.form.addRow(hint_label(tr("settings.asr.chunked.hint")))
        self.form.addRow(self.word_timestamps_check)
        self.form.addRow(self.diarization_box)
        self.form.addRow(self.uncertain_words_check)
        self.form.addRow(tr("settings.asr.word_threshold"), self.word_threshold_spin)
        self.form.addRow(tr("settings.asr.vocabulary"), self.vocabulary_edit)
        self.form.addRow(hint_label(tr("settings.asr.vocabulary.hint")))
        self.form.addRow(section_label(tr("settings.asr.draft_style")))
        self.form.addRow(self.verbatim_check)
        self.form.addRow(hint_label(tr("settings.asr.verbatim.hint")))
        self.form.addRow(self.expand_abbreviations_check)
        self.form.addRow(hint_label(tr("settings.asr.expand_abbreviations.hint")))
        self.form.addRow(self.lowercase_plain_check)
        self.form.addRow(hint_label(tr("settings.asr.lowercase_plain.hint")))

    def load(self, settings: Settings) -> None:
        asr = settings.asr
        self.models_root_edit.setText(asr.models_root)
        select_data(self.device_combo, asr.device)
        self.chunked_check.setChecked(asr.chunked)
        self.word_timestamps_check.setChecked(asr.word_timestamps)
        self.diarization_box.set_value(asr.diarize)
        self.diarization_box.set_speakers(asr.diarize_speakers)
        self.uncertain_words_check.setChecked(asr.show_uncertain_words)
        self.word_threshold_spin.setValue(asr.word_threshold_pct)
        self.word_threshold_spin.setEnabled(asr.show_uncertain_words)
        self.vocabulary_edit.setPlainText(asr.vocabulary)
        self.expand_abbreviations_check.setChecked(asr.expand_abbreviations)
        self.lowercase_plain_check.setChecked(asr.lowercase_plain)
        self.verbatim_check.setChecked(asr.verbatim)

    def apply(self, settings: Settings) -> Settings:
        # Model wybiera się w panelu ASR - strona tylko go przenosi dalej.
        return replace(
            settings,
            asr=replace(
                settings.asr,
                models_root=self.models_root_edit.text().strip(),
                device=str(self.device_combo.currentData()),
                vocabulary="\n".join(
                    split_vocabulary(self.vocabulary_edit.toPlainText())
                ),
                chunked=self.chunked_check.isChecked(),
                word_timestamps=self.word_timestamps_check.isChecked(),
                diarize=self.diarization_box.value(),
                diarize_speakers=self.diarization_box.speakers(),
                show_uncertain_words=self.uncertain_words_check.isChecked(),
                word_threshold_pct=self.word_threshold_spin.value(),
                expand_abbreviations=self.expand_abbreviations_check.isChecked(),
                lowercase_plain=self.lowercase_plain_check.isChecked(),
                verbatim=self.verbatim_check.isChecked(),
            ),
        )

    def _choose_models_root(self) -> None:
        start = self.models_root_edit.text() or str(default_models_root())
        directory = QFileDialog.getExistingDirectory(
            self, tr("settings.asr.models_root.dialog"), start
        )
        if directory:
            self.models_root_edit.setText(directory)


def models_root(text: str) -> Path | None:
    return Path(text.strip()) if text.strip() else None
