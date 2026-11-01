"""Zakładka „Odtwarzacz” w ustawieniach: przewijanie, odsłuch i spektrogram."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox

from transkryptor.audio.spectrogram import MAX_HZ_CHOICES, WINDOWS
from transkryptor.i18n import tr
from transkryptor.settings import (
    AUTO_REWIND_RANGE_MS,
    SEGMENT_PREROLL_RANGE_MS,
    SKIP_RANGE_MS,
    Settings,
)
from transkryptor.ui.settings_pages import FormPage


def seconds_spin(range_ms: tuple[int, int]) -> QDoubleSpinBox:
    """Pole czasu w sekundach (ustawienia trzymają milisekundy)."""
    spin = QDoubleSpinBox()
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setRange(range_ms[0] / 1000, range_ms[1] / 1000)
    spin.setSuffix(" s")
    return spin


def to_ms(spin: QDoubleSpinBox) -> int:
    return round(spin.value() * 1000)


def _select(combo: QComboBox, value: object) -> None:
    combo.setCurrentIndex(max(combo.findData(value), 0))


class PlayerPage(FormPage):
    """Przewijanie, auto-cofanie, odsłuch segmentów, śledzenie i spektrogram."""

    def __init__(self) -> None:
        super().__init__()
        self.skip_spin = seconds_spin(SKIP_RANGE_MS)
        self.auto_rewind_check = QCheckBox(tr("settings.player.auto_rewind"))
        self.auto_rewind_spin = seconds_spin(AUTO_REWIND_RANGE_MS)
        self.auto_rewind_check.toggled.connect(self.auto_rewind_spin.setEnabled)
        self.preroll_spin = seconds_spin(SEGMENT_PREROLL_RANGE_MS)
        self.follow_playback_check = QCheckBox(tr("settings.player.follow"))
        self.follow_playback_check.setToolTip(tr("settings.player.follow.tooltip"))
        self.form.addRow(tr("settings.player.skip"), self.skip_spin)
        self.form.addRow(self.auto_rewind_check)
        self.form.addRow(
            tr("settings.player.auto_rewind_length"), self.auto_rewind_spin
        )
        self.form.addRow(tr("settings.player.preroll"), self.preroll_spin)
        self.form.addRow(self.follow_playback_check)
        self.spectrogram_range_combo = QComboBox()
        for max_hz in MAX_HZ_CHOICES:
            self.spectrogram_range_combo.addItem(
                tr("settings.spectrogram.range.value", khz=max_hz // 1000), max_hz
            )
        self.spectrogram_window_combo = QComboBox()
        for window in WINDOWS:
            self.spectrogram_window_combo.addItem(
                tr(f"settings.spectrogram.window.{window}"), window
            )
        self.spectrogram_window_combo.setToolTip(
            tr("settings.spectrogram.window.tooltip")
        )
        self.form.addRow(tr("settings.spectrogram.range"), self.spectrogram_range_combo)
        self.form.addRow(
            tr("settings.spectrogram.window"), self.spectrogram_window_combo
        )

    def load(self, settings: Settings) -> None:
        player = settings.player
        self.skip_spin.setValue(player.skip_ms / 1000)
        self.auto_rewind_check.setChecked(player.auto_rewind_enabled)
        self.auto_rewind_spin.setValue(player.auto_rewind_ms / 1000)
        self.auto_rewind_spin.setEnabled(player.auto_rewind_enabled)
        self.preroll_spin.setValue(player.segment_preroll_ms / 1000)
        self.follow_playback_check.setChecked(player.follow_playback)
        _select(self.spectrogram_range_combo, player.spectrogram_max_hz)
        _select(self.spectrogram_window_combo, player.spectrogram_window)

    def apply(self, settings: Settings) -> Settings:
        # Pola spoza okna (zwinięcie fali, menu „Dźwięk”) zostają bez zmian.
        return replace(
            settings,
            player=replace(
                settings.player,
                skip_ms=to_ms(self.skip_spin),
                auto_rewind_enabled=self.auto_rewind_check.isChecked(),
                auto_rewind_ms=to_ms(self.auto_rewind_spin),
                segment_preroll_ms=to_ms(self.preroll_spin),
                follow_playback=self.follow_playback_check.isChecked(),
                spectrogram_max_hz=int(self.spectrogram_range_combo.currentData()),
                spectrogram_window=str(self.spectrogram_window_combo.currentData()),
            ),
        )
