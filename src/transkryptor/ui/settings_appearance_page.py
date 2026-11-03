"""Zakładka „Wygląd” w ustawieniach: język, motyw, skala, czcionka i animacje."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QComboBox, QFontComboBox, QLabel, QSpinBox

from transkryptor.i18n import LANGUAGES, tr
from transkryptor.settings import (
    EDITOR_ZOOM_RANGE_PCT,
    EDITOR_ZOOM_STEP_PCT,
    FONT_SIZE_RANGE_PT,
    LANGUAGE_SYSTEM,
    THEME_DARK,
    THEME_HIGH_CONTRAST,
    THEME_LIGHT,
    THEME_SYSTEM,
    UI_SCALE_RANGE_PCT,
    UI_SCALE_STEP_PCT,
    Settings,
)
from transkryptor.ui.settings_pages import FormPage
from transkryptor.ui.shortcuts import (
    ZOOM_IN_ID,
    ZOOM_OUT_ID,
    ZOOM_RESET_ID,
    effective_shortcuts,
    native_shortcut,
)
from transkryptor.ui.theme import set_props


def theme_labels() -> dict[str, str]:
    return {
        THEME_SYSTEM: tr("settings.theme.system"),
        THEME_LIGHT: tr("settings.theme.light"),
        THEME_DARK: tr("settings.theme.dark"),
        THEME_HIGH_CONTRAST: tr("settings.theme.high_contrast"),
    }


def language_labels() -> dict[str, str]:
    """Nazwy języków w nich samych - rozpoznawalne niezależnie od bieżącego."""
    return {LANGUAGE_SYSTEM: tr("settings.language.system"), **LANGUAGES}


def percent_spin(
    value_range: tuple[int, int], step: int, accessible_name: str
) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(*value_range)
    spin.setSingleStep(step)
    spin.setSuffix(" %")
    spin.setAccessibleName(accessible_name)
    return spin


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    set_props(label, role="muted")
    return label


def _select(combo: QComboBox, value: object) -> None:
    combo.setCurrentIndex(max(combo.findData(value), 0))


class AppearancePage(FormPage):
    """Język, motyw, skala interfejsu, czcionka i powiększenie edytora."""

    def __init__(self, initial_language: str, initial_ui_scale: int = 100) -> None:
        super().__init__()
        self._initial_language = initial_language
        self._initial_ui_scale = initial_ui_scale
        self._build_fields()
        self._build_layout()

    def _build_fields(self) -> None:
        self.default_font_check = QCheckBox(tr("settings.editor.default_font"))
        self.font_combo = QFontComboBox()
        self.font_combo.setAccessibleName(tr("settings.editor.font"))
        self.default_font_check.toggled.connect(
            lambda checked: self.font_combo.setEnabled(not checked)
        )
        self.font_size_spin = QSpinBox()
        # Wartość 0 („Domyślny”) leży tuż pod zakresem rozmiarów.
        self.font_size_spin.setRange(FONT_SIZE_RANGE_PT[0] - 1, FONT_SIZE_RANGE_PT[1])
        self.font_size_spin.setSpecialValueText(tr("settings.editor.default_size"))
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setAccessibleName(tr("settings.editor.size"))
        self.zoom_spin = percent_spin(
            EDITOR_ZOOM_RANGE_PCT, EDITOR_ZOOM_STEP_PCT, tr("settings.editor.zoom")
        )
        self.zoom_spin.setObjectName("editor_zoom_spin")
        self.theme_combo = QComboBox()
        for value, theme_label in theme_labels().items():
            self.theme_combo.addItem(theme_label, value)
        self.theme_combo.setToolTip(tr("settings.theme.tooltip"))
        self.theme_combo.setAccessibleName(tr("settings.theme"))
        self.language_combo = QComboBox()
        for code, language_label in language_labels().items():
            self.language_combo.addItem(language_label, code)
        self.language_combo.setAccessibleName(tr("settings.language"))
        self.language_hint = _hint(tr("settings.language.restart_hint"))
        self.language_combo.currentIndexChanged.connect(self._update_restart_hints)
        self.ui_scale_spin = percent_spin(
            UI_SCALE_RANGE_PCT, UI_SCALE_STEP_PCT, tr("settings.ui_scale")
        )
        self.ui_scale_spin.setObjectName("ui_scale_spin")
        self.ui_scale_hint = _hint(tr("settings.ui_scale.restart_hint"))
        self.ui_scale_spin.valueChanged.connect(self._update_restart_hints)
        self.reduce_motion_check = QCheckBox(tr("settings.reduce_motion"))
        self.reduce_motion_check.setObjectName("reduce_motion_check")
        self.zoom_hint = _hint("")

    def _build_layout(self) -> None:
        self.form.addRow(tr("settings.language"), self.language_combo)
        self.form.addRow(self.language_hint)
        self.form.addRow(tr("settings.theme"), self.theme_combo)
        self.form.addRow(_hint(tr("settings.theme.high_contrast.hint")))
        self.form.addRow(tr("settings.ui_scale"), self.ui_scale_spin)
        self.form.addRow(self.ui_scale_hint)
        self.form.addRow(self.reduce_motion_check)
        self.form.addRow(self.default_font_check)
        self.form.addRow(tr("settings.editor.font"), self.font_combo)
        self.form.addRow(tr("settings.editor.size"), self.font_size_spin)
        self.form.addRow(tr("settings.editor.zoom"), self.zoom_spin)
        self.form.addRow(self.zoom_hint)

    def load(self, settings: Settings) -> None:
        appearance = settings.appearance
        _select(self.theme_combo, appearance.theme)
        _select(self.language_combo, appearance.language)
        self.ui_scale_spin.setValue(appearance.ui_scale_pct)
        self.reduce_motion_check.setChecked(appearance.reduce_motion)
        self._update_restart_hints()
        editor = settings.editor
        self.default_font_check.setChecked(not editor.font_family)
        self.font_combo.setEnabled(bool(editor.font_family))
        if editor.font_family:
            self.font_combo.setCurrentFont(QFont(editor.font_family))
        self.font_size_spin.setValue(
            editor.font_size_pt or self.font_size_spin.minimum()
        )
        self.zoom_spin.setValue(editor.zoom_pct)
        shortcuts = effective_shortcuts(settings.shortcuts.overrides)

        def first(action_id: str) -> str:
            sequences = shortcuts.get(action_id, ())
            return native_shortcut(sequences[0]) if sequences else "-"

        self.zoom_hint.setText(
            tr(
                "settings.editor.zoom.hint",
                zoom_in=first(ZOOM_IN_ID),
                zoom_out=first(ZOOM_OUT_ID),
                zoom_reset=first(ZOOM_RESET_ID),
            )
        )

    def apply(self, settings: Settings) -> Settings:
        size = self.font_size_spin.value()
        return replace(
            settings,
            appearance=replace(
                settings.appearance,
                theme=str(self.theme_combo.currentData()),
                language=str(self.language_combo.currentData()),
                ui_scale_pct=self.ui_scale_spin.value(),
                reduce_motion=self.reduce_motion_check.isChecked(),
            ),
            editor=replace(
                settings.editor,
                font_family=(
                    ""
                    if self.default_font_check.isChecked()
                    else self.font_combo.currentFont().family()
                ),
                font_size_pt=0 if size == self.font_size_spin.minimum() else size,
                zoom_pct=self.zoom_spin.value(),
            ),
        )

    def _update_restart_hints(self) -> None:
        """Komunikaty o restarcie tylko po zmianie względem bieżących wartości."""
        language_changed = self.language_combo.currentData() != self._initial_language
        self.language_hint.setVisible(language_changed)
        scale_changed = self.ui_scale_spin.value() != self._initial_ui_scale
        self.ui_scale_hint.setVisible(scale_changed)
