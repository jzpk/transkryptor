"""Okno „Ustawienia…”: preferencje użytkownika pogrupowane w sekcje.

Okno tylko edytuje kopię ustawień; zapis i powiadomienie komponentów
wykonuje ``SettingsStore`` po zatwierdzeniu. Kolejne funkcje dodają własne
sekcje (``QGroupBox``) — bez jednej długiej listy pól.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.settings import (
    AUTO_REWIND_RANGE_MS,
    FONT_SIZE_RANGE_PT,
    SEGMENT_PREROLL_RANGE_MS,
    SKIP_RANGE_MS,
    EditorSettings,
    NotationSettings,
    PlayerSettings,
    Settings,
)
from transkryptor.ui.theme import set_props

DIALOG_TITLE = "Ustawienia"
DEFAULT_FONT_LABEL = "Domyślna"
DEFAULT_SIZE_LABEL = "Domyślny"
ELLIPSIS_STYLE_LABELS = {
    EllipsisStyle.UNICODE: "…  (jeden znak, U+2026)",
    EllipsisStyle.ASCII: "...  (trzy kropki)",
}
ELLIPSIS_CHANGE_HINT = (
    "Istniejący tekst się nie zmienia — nowe pauzy i walidacja użyją "
    "nowego zapisu. Starsze wielokropki zamienisz akcją "
    "„Ujednolić wielokropki” nad listą ostrzeżeń."
)


class SettingsDialog(QDialog):
    """Okno edycji ustawień; wynik odczytuje się metodą ``settings()``."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(DIALOG_TITLE)
        self.setObjectName("settings_dialog")

        self.skip_spin = _seconds_spin(SKIP_RANGE_MS)
        self.auto_rewind_check = QCheckBox("Cofaj nagranie przy wznowieniu po pauzie")
        self.auto_rewind_spin = _seconds_spin(AUTO_REWIND_RANGE_MS)
        self.auto_rewind_check.toggled.connect(self.auto_rewind_spin.setEnabled)
        self.preroll_spin = _seconds_spin(SEGMENT_PREROLL_RANGE_MS)

        player_form = QFormLayout()
        player_form.addRow("Skok w przód i w tył:", self.skip_spin)
        player_form.addRow(self.auto_rewind_check)
        player_form.addRow("Długość auto-cofania:", self.auto_rewind_spin)
        player_form.addRow("Start przed segmentem ASR:", self.preroll_spin)
        player_group = QGroupBox("Odtwarzacz")
        player_group.setLayout(player_form)

        self.default_font_check = QCheckBox(f"{DEFAULT_FONT_LABEL} czcionka")
        self.font_combo = QFontComboBox()
        self.default_font_check.toggled.connect(
            lambda checked: self.font_combo.setEnabled(not checked)
        )
        self.font_size_spin = QSpinBox()
        # Wartość 0 („Domyślny”) leży tuż pod zakresem rozmiarów.
        self.font_size_spin.setRange(FONT_SIZE_RANGE_PT[0] - 1, FONT_SIZE_RANGE_PT[1])
        self.font_size_spin.setSpecialValueText(DEFAULT_SIZE_LABEL)
        self.font_size_spin.setSuffix(" pt")

        font_row = QHBoxLayout()
        font_row.addWidget(self.default_font_check)
        font_row.addWidget(self.font_combo, stretch=1)
        editor_form = QFormLayout()
        editor_form.addRow("Czcionka tekstu:", font_row)
        editor_form.addRow("Rozmiar tekstu:", self.font_size_spin)
        editor_group = QGroupBox("Edytor")
        editor_group.setLayout(editor_form)

        self.ellipsis_combo = QComboBox()
        for style, label in ELLIPSIS_STYLE_LABELS.items():
            self.ellipsis_combo.addItem(label, style.value)
        self.ellipsis_hint = QLabel(ELLIPSIS_CHANGE_HINT)
        self.ellipsis_hint.setWordWrap(True)
        set_props(self.ellipsis_hint, role="muted")
        self.ellipsis_combo.currentIndexChanged.connect(self._update_ellipsis_hint)
        notation_form = QFormLayout()
        notation_form.addRow("Styl wielokropka:", self.ellipsis_combo)
        notation_form.addRow(self.ellipsis_hint)
        notation_group = QGroupBox("Notacja")
        notation_group.setLayout(notation_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.restore_defaults_button: QPushButton = buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.restore_defaults_button.setText("Przywróć domyślne")
        self.restore_defaults_button.clicked.connect(
            lambda: self.set_settings(Settings())
        )

        layout = QVBoxLayout(self)
        layout.addWidget(player_group)
        layout.addWidget(editor_group)
        layout.addWidget(notation_group)
        layout.addWidget(buttons)

        self._initial_ellipsis_style = settings.notation.ellipsis_style
        self.set_settings(settings)

    def set_settings(self, settings: Settings) -> None:
        """Wypełnia pola wartościami ``settings``."""
        player = settings.player
        self.skip_spin.setValue(player.skip_ms / 1000)
        self.auto_rewind_check.setChecked(player.auto_rewind_enabled)
        self.auto_rewind_spin.setValue(player.auto_rewind_ms / 1000)
        self.auto_rewind_spin.setEnabled(player.auto_rewind_enabled)
        self.preroll_spin.setValue(player.segment_preroll_ms / 1000)

        editor = settings.editor
        self.default_font_check.setChecked(not editor.font_family)
        self.font_combo.setEnabled(bool(editor.font_family))
        if editor.font_family:
            self.font_combo.setCurrentFont(QFont(editor.font_family))
        self.font_size_spin.setValue(
            editor.font_size_pt or self.font_size_spin.minimum()
        )

        index = self.ellipsis_combo.findData(settings.notation.ellipsis_style)
        self.ellipsis_combo.setCurrentIndex(max(index, 0))
        self._update_ellipsis_hint()

    def _update_ellipsis_hint(self) -> None:
        """Podpowiedź „Ujednolić” tylko po zmianie stylu względem bieżącego."""
        changed = self.ellipsis_combo.currentData() != self._initial_ellipsis_style
        self.ellipsis_hint.setVisible(changed)

    def settings(self) -> Settings:
        """Ustawienia odpowiadające bieżącym wartościom pól."""
        size = self.font_size_spin.value()
        return Settings(
            player=PlayerSettings(
                skip_ms=_ms(self.skip_spin),
                auto_rewind_enabled=self.auto_rewind_check.isChecked(),
                auto_rewind_ms=_ms(self.auto_rewind_spin),
                segment_preroll_ms=_ms(self.preroll_spin),
            ),
            editor=EditorSettings(
                font_family=(
                    ""
                    if self.default_font_check.isChecked()
                    else self.font_combo.currentFont().family()
                ),
                font_size_pt=0 if size == self.font_size_spin.minimum() else size,
            ),
            notation=NotationSettings(
                ellipsis_style=str(self.ellipsis_combo.currentData())
            ),
        )


def _seconds_spin(range_ms: tuple[int, int]) -> QDoubleSpinBox:
    """Pole czasu w sekundach (ustawienia trzymają milisekundy)."""
    spin = QDoubleSpinBox()
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setRange(range_ms[0] / 1000, range_ms[1] / 1000)
    spin.setSuffix(" s")
    return spin


def _ms(spin: QDoubleSpinBox) -> int:
    return round(spin.value() * 1000)
