"""Zakładka „Projekt” w ustawieniach: autozapis, dzienny cel i folder zapisu."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from transkryptor.i18n import tr
from transkryptor.settings import (
    AUTOSAVE_INTERVAL_RANGE_S,
    DAILY_GOAL_RANGE_MIN,
    Settings,
)
from transkryptor.ui.save_location import default_save_dir
from transkryptor.ui.settings_pages import FormPage


class ProjectPage(FormPage):
    """Autozapis projektu, dzienny cel pracy i folder zapisu plików."""

    def __init__(self) -> None:
        super().__init__()
        self._build_save_dir()
        self._build_autosave()
        self._build_daily_goal()

    def _build_save_dir(self) -> None:
        """Folder zapisu: puste pole - folder domyślny w Dokumentach."""
        self.save_dir_edit = QLineEdit()
        self.save_dir_edit.setObjectName("settings_save_dir")
        self.save_dir_edit.setPlaceholderText(str(default_save_dir()))
        self.save_dir_edit.setClearButtonEnabled(True)
        self.save_dir_edit.setToolTip(tr("settings.save_dir.tooltip"))
        self.save_dir_button = QPushButton(tr("settings.save_dir.choose"))
        self.save_dir_button.clicked.connect(self._choose_save_dir)
        row = QHBoxLayout()
        row.addWidget(self.save_dir_edit, stretch=1)
        row.addWidget(self.save_dir_button)
        self.form.addRow(tr("settings.save_dir"), row)

    def _build_autosave(self) -> None:
        self.autosave_check = QCheckBox(tr("settings.autosave"))
        self.autosave_check.setToolTip(tr("settings.autosave.tooltip"))
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(*AUTOSAVE_INTERVAL_RANGE_S)
        self.autosave_spin.setSingleStep(30)
        self.autosave_spin.setSuffix(" s")
        self.autosave_check.toggled.connect(self.autosave_spin.setEnabled)
        self.form.addRow(self.autosave_check)
        self.form.addRow(tr("settings.autosave.interval"), self.autosave_spin)

    def _build_daily_goal(self) -> None:
        # Dzienny cel: 0 (pozycja „Bez celu”) wyłącza podgląd w pasku stanu.
        self.daily_goal_spin = QSpinBox()
        self.daily_goal_spin.setRange(0, DAILY_GOAL_RANGE_MIN[1])
        self.daily_goal_spin.setSingleStep(5)
        self.daily_goal_spin.setSuffix(tr("settings.daily_goal.suffix"))
        self.daily_goal_spin.setSpecialValueText(tr("settings.daily_goal.off"))
        self.daily_goal_spin.setToolTip(tr("settings.daily_goal.tooltip"))
        self.form.addRow(tr("settings.daily_goal"), self.daily_goal_spin)

    def load(self, settings: Settings) -> None:
        self.save_dir_edit.setText(settings.project.save_dir)
        self.autosave_check.setChecked(settings.project.autosave_enabled)
        self.autosave_spin.setValue(settings.project.autosave_interval_s)
        self.autosave_spin.setEnabled(settings.project.autosave_enabled)
        self.daily_goal_spin.setValue(settings.project.daily_goal_min)

    def apply(self, settings: Settings) -> Settings:
        return replace(
            settings,
            project=replace(
                settings.project,
                autosave_enabled=self.autosave_check.isChecked(),
                autosave_interval_s=self.autosave_spin.value(),
                daily_goal_min=self.daily_goal_spin.value(),
                save_dir=self.save_dir_edit.text().strip(),
            ),
        )

    def _choose_save_dir(self) -> None:
        start = self.save_dir_edit.text().strip() or str(default_save_dir().parent)
        directory = QFileDialog.getExistingDirectory(
            self, tr("settings.save_dir.dialog"), start
        )
        if directory:
            self.save_dir_edit.setText(directory)
