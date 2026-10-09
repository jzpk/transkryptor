"""Okno „Ustawienia…”: preferencje użytkownika pogrupowane w sekcje.

Okno tylko edytuje kopię ustawień; zapis i powiadomienie komponentów
wykonuje ``SettingsStore`` po zatwierdzeniu. Kolejne funkcje dodają własne
sekcje (``QGroupBox``) — bez jednej długiej listy pól.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    DEFAULT_KEYS,
    MetadataField,
    encode_fields,
    new_custom_field,
)
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.settings import (
    AUTO_REWIND_RANGE_MS,
    AUTOSAVE_INTERVAL_RANGE_S,
    FONT_SIZE_RANGE_PT,
    SEGMENT_PREROLL_RANGE_MS,
    SKIP_RANGE_MS,
    EditorSettings,
    MetadataSettings,
    NotationSettings,
    PlayerSettings,
    ProjectSettings,
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

        self.autosave_check = QCheckBox("Autozapis bieżącej pracy")
        self.autosave_check.setToolTip(
            "Kopia stanu pracy w katalogu danych aplikacji, usuwana po "
            "poprawnym zamknięciu; pozwala odzyskać pracę po awarii"
        )
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(*AUTOSAVE_INTERVAL_RANGE_S)
        self.autosave_spin.setSingleStep(30)
        self.autosave_spin.setSuffix(" s")
        self.autosave_check.toggled.connect(self.autosave_spin.setEnabled)
        project_form = QFormLayout()
        project_form.addRow(self.autosave_check)
        project_form.addRow("Interwał autozapisu:", self.autosave_spin)
        project_group = QGroupBox("Projekt")
        project_group.setLayout(project_form)

        self.metadata_table = QTableWidget(0, 2)
        self.metadata_table.setHorizontalHeaderLabels(["Pole", "Dane osobowe"])
        self.metadata_table.verticalHeader().setVisible(False)
        header = self.metadata_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.metadata_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.metadata_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.metadata_table.setMinimumWidth(320)
        metadata_hint = QLabel(
            "Zaznaczone pola są w formularzu metryczki i w eksporcie DOCX, "
            "w tej kolejności. Pola osobowe pomija eksport anonimizowany."
        )
        metadata_hint.setWordWrap(True)
        set_props(metadata_hint, role="muted")
        self.field_up_button = QPushButton("Wyżej")
        self.field_down_button = QPushButton("Niżej")
        self.add_field_button = QPushButton("Dodaj pole…")
        self.remove_field_button = QPushButton("Usuń pole")
        self.remove_field_button.setToolTip("Usuwa pole dodane przez zespół")
        self.field_up_button.clicked.connect(lambda: self._move_field(-1))
        self.field_down_button.clicked.connect(lambda: self._move_field(1))
        self.add_field_button.clicked.connect(self._on_add_field)
        self.remove_field_button.clicked.connect(self._remove_field)
        self.metadata_table.currentCellChanged.connect(
            lambda *_args: self._update_field_buttons()
        )
        field_buttons = QHBoxLayout()
        for button in (
            self.field_up_button,
            self.field_down_button,
            self.add_field_button,
            self.remove_field_button,
        ):
            field_buttons.addWidget(button)
        metadata_layout = QVBoxLayout()
        metadata_layout.addWidget(metadata_hint)
        metadata_layout.addWidget(self.metadata_table, stretch=1)
        metadata_layout.addLayout(field_buttons)
        metadata_group = QGroupBox("Metryczka")
        metadata_group.setLayout(metadata_layout)

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

        left = QVBoxLayout()
        left.addWidget(player_group)
        left.addWidget(editor_group)
        left.addWidget(notation_group)
        left.addWidget(project_group)
        left.addStretch(1)
        columns = QHBoxLayout()
        columns.addLayout(left)
        columns.addWidget(metadata_group, stretch=1)
        layout = QVBoxLayout(self)
        layout.addLayout(columns)
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

        self.autosave_check.setChecked(settings.project.autosave_enabled)
        self.autosave_spin.setValue(settings.project.autosave_interval_s)
        self.autosave_spin.setEnabled(settings.project.autosave_enabled)

        self.set_metadata_fields(settings.metadata.fields)

    # --- metryczka -----------------------------------------------------------

    def set_metadata_fields(self, fields: tuple[MetadataField, ...]) -> None:
        self.metadata_table.setRowCount(0)
        for metadata_field in fields:
            self._append_field(metadata_field)
        self.metadata_table.setCurrentCell(-1, -1)
        self._update_field_buttons()

    def metadata_fields(self) -> tuple[MetadataField, ...]:
        fields: list[MetadataField] = []
        for row in range(self.metadata_table.rowCount()):
            name_item = self.metadata_table.item(row, 0)
            personal_item = self.metadata_table.item(row, 1)
            if name_item is None or personal_item is None:
                continue
            key = str(name_item.data(Qt.ItemDataRole.UserRole))
            label = name_item.text().strip() or _default_label(key)
            fields.append(
                MetadataField(
                    key,
                    label,
                    personal=personal_item.checkState() == Qt.CheckState.Checked,
                    enabled=name_item.checkState() == Qt.CheckState.Checked,
                )
            )
        return tuple(fields)

    def add_custom_field(self, label: str, personal: bool = False) -> None:
        """Dodaje własne pole zespołu na końcu listy."""
        if not label.strip():
            return
        self._append_field(new_custom_field(label, personal))
        self.metadata_table.setCurrentCell(self.metadata_table.rowCount() - 1, 0)

    def _append_field(self, metadata_field: MetadataField) -> None:
        row = self.metadata_table.rowCount()
        self.metadata_table.insertRow(row)
        name_item = QTableWidgetItem(metadata_field.label)
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        if metadata_field.is_custom:
            flags |= Qt.ItemFlag.ItemIsEditable
        name_item.setFlags(flags)
        name_item.setData(Qt.ItemDataRole.UserRole, metadata_field.key)
        name_item.setCheckState(_check(metadata_field.enabled))
        personal_item = QTableWidgetItem()
        personal_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        personal_item.setCheckState(_check(metadata_field.personal))
        self.metadata_table.setItem(row, 0, name_item)
        self.metadata_table.setItem(row, 1, personal_item)

    def _on_add_field(self) -> None:
        label, accepted = QInputDialog.getText(self, "Nowe pole metryczki", "Etykieta:")
        if accepted:
            self.add_custom_field(label)

    def _move_field(self, delta: int) -> None:
        fields = list(self.metadata_fields())
        row = self.metadata_table.currentRow()
        target = row + delta
        if not (0 <= row < len(fields) and 0 <= target < len(fields)):
            return
        fields[row], fields[target] = fields[target], fields[row]
        self.set_metadata_fields(tuple(fields))
        self.metadata_table.setCurrentCell(target, 0)

    def _remove_field(self) -> None:
        row = self.metadata_table.currentRow()
        fields = self.metadata_fields()
        if 0 <= row < len(fields) and fields[row].is_custom:
            self.metadata_table.removeRow(row)
        self._update_field_buttons()

    def _update_field_buttons(self) -> None:
        row = self.metadata_table.currentRow()
        count = self.metadata_table.rowCount()
        item = self.metadata_table.item(row, 0) if row >= 0 else None
        custom = (
            item is not None and item.data(Qt.ItemDataRole.UserRole) not in DEFAULT_KEYS
        )
        self.field_up_button.setEnabled(row > 0)
        self.field_down_button.setEnabled(0 <= row < count - 1)
        self.remove_field_button.setEnabled(custom)

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
            project=ProjectSettings(
                autosave_enabled=self.autosave_check.isChecked(),
                autosave_interval_s=self.autosave_spin.value(),
            ),
            metadata=MetadataSettings(fields_spec=_fields_spec(self.metadata_fields())),
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


def _check(checked: bool) -> Qt.CheckState:
    return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked


def _default_label(key: str) -> str:
    return next((f.label for f in DEFAULT_FIELDS if f.key == key), key)


def _fields_spec(fields: tuple[MetadataField, ...]) -> str:
    """Zestaw domyślny zapisuje się jako pusty napis (łatwe przyszłe zmiany)."""
    return "" if fields == DEFAULT_FIELDS else encode_fields(fields)
