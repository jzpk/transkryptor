"""Zakładki okna „Ustawienia…”: każda edytuje jedną część ustawień.

Strona spełnia protokół :class:`SettingsPage`: ``load`` wypełnia pola
z ustawień, a ``apply`` zwraca kopię ustawień z wartościami pól strony
(pola spoza strony zostają bez zmian). Nowa sekcja ustawień to nowa klasa
strony dopisana do listy w ``SettingsDialog``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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
    enabled_fields,
    encode_fields,
    new_custom_field,
)
from transkryptor.export.docx_template import (
    TemplateCheck,
    check_template,
    suggested_placeholders,
)
from transkryptor.export.options import UNTIMED_MODES
from transkryptor.export.superscript import MODES as SUPERSCRIPT_MODES
from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.notation.validator import SEVERITY_HINT, VALIDATOR_RULES
from transkryptor.settings import (
    AUTOSAVE_INTERVAL_RANGE_S,
    DAILY_GOAL_RANGE_MIN,
    Settings,
    encode_bool_map,
    encode_shortcut_map,
    encode_snippets,
)
from transkryptor.ui.shortcuts import find_conflicts, shortcut_overrides
from transkryptor.ui.shortcuts_editor import ShortcutsEditor, SnippetsEditor
from transkryptor.ui.theme import set_props


class SettingsPage(Protocol):
    """Strona ustawień: wypełnienie pól i odczyt wartości do ustawień."""

    def load(self, settings: Settings) -> None: ...

    def apply(self, settings: Settings) -> Settings: ...


def device_labels() -> dict[str, str]:
    return {
        "auto": tr("settings.asr.device.auto"),
        "cpu": tr("settings.asr.device.cpu"),
    }


def ellipsis_style_labels() -> dict[EllipsisStyle, str]:
    return {
        EllipsisStyle.UNICODE: tr("settings.ellipsis.unicode"),
        EllipsisStyle.ASCII: tr("settings.ellipsis.ascii"),
    }


class FormPage(QScrollArea):
    """Strona z formularzem przy górnej krawędzi.

    Długi formularz (np. ASR) przewija się w pionie zamiast ściskać pola
    w niskim oknie.
    """

    def __init__(self) -> None:
        super().__init__()
        self.form = QFormLayout()
        self.form.setContentsMargins(16, 16, 16, 16)
        self.form.setVerticalSpacing(10)
        content = QWidget()
        content.setObjectName("settings_page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.form)
        layout.addStretch(1)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidget(content)


class NotationPage(FormPage):
    """Styl wielokropka i podpowiedzi wstawek w edytorze."""

    def __init__(self, initial_ellipsis_style: str) -> None:
        super().__init__()
        self._initial_ellipsis_style = initial_ellipsis_style
        self.ellipsis_combo = QComboBox()
        for style, label in ellipsis_style_labels().items():
            self.ellipsis_combo.addItem(label, style.value)
        self.ellipsis_hint = QLabel(tr("settings.ellipsis.change_hint"))
        self.ellipsis_hint.setWordWrap(True)
        set_props(self.ellipsis_hint, role="muted")
        self.ellipsis_combo.currentIndexChanged.connect(self._update_ellipsis_hint)
        self.autocomplete_check = QCheckBox(tr("settings.editor.autocomplete"))
        autocomplete_hint = QLabel(tr("settings.editor.autocomplete.hint"))
        autocomplete_hint.setWordWrap(True)
        set_props(autocomplete_hint, role="muted")
        self.form.addRow(tr("settings.ellipsis.style"), self.ellipsis_combo)
        self.form.addRow(self.ellipsis_hint)
        self.form.addRow(self.autocomplete_check)
        self.form.addRow(autocomplete_hint)

    def load(self, settings: Settings) -> None:
        select_data(self.ellipsis_combo, settings.notation.ellipsis_style)
        self._update_ellipsis_hint()
        self.autocomplete_check.setChecked(settings.editor.autocomplete)

    def apply(self, settings: Settings) -> Settings:
        return replace(
            settings,
            notation=replace(
                settings.notation, ellipsis_style=str(self.ellipsis_combo.currentData())
            ),
            editor=replace(
                settings.editor, autocomplete=self.autocomplete_check.isChecked()
            ),
        )

    def _update_ellipsis_hint(self) -> None:
        """Podpowiedź „Ujednolić” tylko po zmianie stylu względem bieżącego."""
        changed = self.ellipsis_combo.currentData() != self._initial_ellipsis_style
        self.ellipsis_hint.setVisible(changed)


class ValidatorPage(FormPage):
    """Reguły walidatora notacji włączane pojedynczo."""

    def __init__(self) -> None:
        super().__init__()
        validator_hint = QLabel(tr("settings.validator.hint"))
        validator_hint.setWordWrap(True)
        set_props(validator_hint, role="muted")
        self.form.addRow(validator_hint)
        self.validator_checks: dict[str, QCheckBox] = {}
        for rule in VALIDATOR_RULES:
            text = rule.label
            if rule.severity == SEVERITY_HINT:
                text = tr("settings.validator.hint_rule", rule=text)
            checkbox = QCheckBox(text)
            self.form.addRow(checkbox)
            self.validator_checks[rule.code] = checkbox

    def load(self, settings: Settings) -> None:
        enabled = settings.validator.enabled
        for code, checkbox in self.validator_checks.items():
            checkbox.setChecked(code in enabled)

    def apply(self, settings: Settings) -> Settings:
        overrides = {
            rule.code: self.validator_checks[rule.code].isChecked()
            for rule in VALIDATOR_RULES
            if self.validator_checks[rule.code].isChecked() != rule.default_enabled
        }
        return replace(
            settings,
            validator=replace(
                settings.validator, overrides_spec=encode_bool_map(overrides)
            ),
        )


class ShortcutPages:
    """Zakładki „Skróty” i „Wstawki” z wspólnym sprawdzaniem konfliktów."""

    def __init__(self) -> None:
        self.shortcuts_editor = ShortcutsEditor()
        self.snippets_editor = SnippetsEditor()
        self.shortcuts_editor.changed.connect(self._update_conflicts)
        self.snippets_editor.changed.connect(self._update_conflicts)

    def load(self, settings: Settings) -> None:
        self.shortcuts_editor.set_overrides(settings.shortcuts.overrides)
        self.snippets_editor.set_taken_shortcuts(
            s for seqs in self.shortcuts_editor.mapping().values() for s in seqs
        )
        self.snippets_editor.set_snippets(settings.snippets.snippets)
        self._update_conflicts()

    def apply(self, settings: Settings) -> Settings:
        return replace(
            settings,
            shortcuts=replace(
                settings.shortcuts,
                overrides_spec=encode_shortcut_map(
                    shortcut_overrides(self.shortcuts_editor.mapping())
                ),
            ),
            snippets=replace(
                settings.snippets, spec=encode_snippets(self.snippets_editor.snippets())
            ),
        )

    def conflicts(self) -> list[str]:
        """Opisy konfliktów skrótów akcji i wstawek (ACC-43)."""
        mapping = {
            **self.shortcuts_editor.mapping(),
            **self.snippets_editor.shortcut_mapping(),
        }
        return [conflict.message for conflict in find_conflicts(mapping)]

    def _update_conflicts(self) -> None:
        self.shortcuts_editor.conflicts_label.setText("\n".join(self.conflicts()))


class ProjectPage(FormPage):
    """Autozapis projektu i dzienny cel pracy."""

    def __init__(self) -> None:
        super().__init__()
        self.autosave_check = QCheckBox(tr("settings.autosave"))
        self.autosave_check.setToolTip(tr("settings.autosave.tooltip"))
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(*AUTOSAVE_INTERVAL_RANGE_S)
        self.autosave_spin.setSingleStep(30)
        self.autosave_spin.setSuffix(" s")
        self.autosave_check.toggled.connect(self.autosave_spin.setEnabled)
        self.form.addRow(self.autosave_check)
        self.form.addRow(tr("settings.autosave.interval"), self.autosave_spin)
        # Dzienny cel: 0 (pozycja „Bez celu”) wyłącza podgląd w pasku stanu.
        self.daily_goal_spin = QSpinBox()
        self.daily_goal_spin.setRange(0, DAILY_GOAL_RANGE_MIN[1])
        self.daily_goal_spin.setSingleStep(5)
        self.daily_goal_spin.setSuffix(tr("settings.daily_goal.suffix"))
        self.daily_goal_spin.setSpecialValueText(tr("settings.daily_goal.off"))
        self.daily_goal_spin.setToolTip(tr("settings.daily_goal.tooltip"))
        self.form.addRow(tr("settings.daily_goal"), self.daily_goal_spin)

    def load(self, settings: Settings) -> None:
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
            ),
        )


class MetadataPage(QWidget):
    """Pola metryczki zespołu: kolejność, włączenie, dane osobowe, własne pola."""

    def __init__(self) -> None:
        super().__init__()
        self.metadata_table = QTableWidget(0, 2)
        self.metadata_table.setHorizontalHeaderLabels(
            [tr("settings.metadata.field"), tr("settings.metadata.personal")]
        )
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
        metadata_hint = QLabel(tr("settings.metadata.hint"))
        metadata_hint.setWordWrap(True)
        set_props(metadata_hint, role="muted")
        self.field_up_button = QPushButton(tr("settings.metadata.up"))
        self.field_down_button = QPushButton(tr("settings.metadata.down"))
        self.add_field_button = QPushButton(tr("settings.metadata.add"))
        self.remove_field_button = QPushButton(tr("settings.metadata.remove"))
        self.remove_field_button.setToolTip(tr("settings.metadata.remove.tooltip"))
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(metadata_hint)
        layout.addWidget(self.metadata_table, stretch=1)
        layout.addLayout(field_buttons)

    def load(self, settings: Settings) -> None:
        self.set_fields(settings.metadata.fields)

    def apply(self, settings: Settings) -> Settings:
        return replace(
            settings,
            metadata=replace(
                settings.metadata, fields_spec=_fields_spec(self.fields())
            ),
        )

    def set_fields(self, fields: tuple[MetadataField, ...]) -> None:
        self.metadata_table.setRowCount(0)
        for metadata_field in fields:
            self._append_field(metadata_field)
        self.metadata_table.setCurrentCell(-1, -1)
        self._update_field_buttons()

    def fields(self) -> tuple[MetadataField, ...]:
        fields: list[MetadataField] = []
        for row in range(self.metadata_table.rowCount()):
            name_item = self.metadata_table.item(row, 0)
            personal_item = self.metadata_table.item(row, 1)
            if name_item is None or personal_item is None:
                continue
            key = str(name_item.data(Qt.ItemDataRole.UserRole))
            label = (
                _default_label(key)
                if key in DEFAULT_KEYS
                else name_item.text().strip() or key
            )
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
        name_item = QTableWidgetItem(metadata_field.display_label)
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
        label, accepted = QInputDialog.getText(
            self, tr("settings.metadata.new_title"), tr("settings.metadata.new_label")
        )
        if accepted:
            self.add_custom_field(label)

    def _move_field(self, delta: int) -> None:
        fields = list(self.fields())
        row = self.metadata_table.currentRow()
        target = row + delta
        if not (0 <= row < len(fields) and 0 <= target < len(fields)):
            return
        fields[row], fields[target] = fields[target], fields[row]
        self.set_fields(tuple(fields))
        self.metadata_table.setCurrentCell(target, 0)

    def _remove_field(self) -> None:
        row = self.metadata_table.currentRow()
        fields = self.fields()
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


class ExportPage(FormPage):
    """Szablon DOCX i domyślne opcje formatów tekstowych (faza 12)."""

    def __init__(self, fields: Callable[[], tuple[MetadataField, ...]]) -> None:
        super().__init__()
        self._fields = fields
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText(tr("settings.export.template.builtin"))
        self.template_edit.setClearButtonEnabled(True)
        self.template_edit.editingFinished.connect(self.check_template)
        self.template_edit.textChanged.connect(
            lambda text: text or self.check_template()
        )
        self.template_button = QPushButton(tr("settings.export.template.choose"))
        self.template_button.clicked.connect(self._choose_template)
        template_row = QHBoxLayout()
        template_row.addWidget(self.template_edit, stretch=1)
        template_row.addWidget(self.template_button)
        self.template_status = QLabel()
        self.template_status.setWordWrap(True)
        self.template_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.placeholders_hint = QLabel()
        self.placeholders_hint.setWordWrap(True)
        self.placeholders_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        set_props(self.placeholders_hint, role="muted")
        self.superscript_mode_combo = QComboBox()
        for mode in SUPERSCRIPT_MODES:
            self.superscript_mode_combo.addItem(tr(f"export.superscript.{mode}"), mode)
        self.untimed_mode_combo = QComboBox()
        for mode in UNTIMED_MODES:
            self.untimed_mode_combo.addItem(tr(f"export.untimed.{mode}"), mode)
        self.form.addRow(tr("settings.export.template"), template_row)
        self.form.addRow(self.template_status)
        self.form.addRow(self.placeholders_hint)
        self.form.addRow(tr("export_dialog.superscript"), self.superscript_mode_combo)
        self.form.addRow(tr("export_dialog.untimed"), self.untimed_mode_combo)

    def load(self, settings: Settings) -> None:
        self.template_edit.setText(settings.export.template_path)
        select_data(self.superscript_mode_combo, settings.export.superscript_mode)
        select_data(self.untimed_mode_combo, settings.export.untimed_mode)
        self.check_template()

    def apply(self, settings: Settings) -> Settings:
        # Ostatni format okna „Eksportuj jako…” nie jest polem tej strony.
        return replace(
            settings,
            export=replace(
                settings.export,
                template_path=self.template_edit.text().strip(),
                superscript_mode=str(self.superscript_mode_combo.currentData()),
                untimed_mode=str(self.untimed_mode_combo.currentData()),
            ),
        )

    def _choose_template(self) -> None:
        start = self.template_edit.text().strip()
        path, _selected = QFileDialog.getOpenFileName(
            self,
            tr("settings.export.template.dialog"),
            str(Path(start).parent) if start else "",
            tr("export.filter"),
        )
        if path:
            self.template_edit.setText(path)
            self.check_template()

    def check_template(self) -> TemplateCheck | None:
        """ACC-56: walidacja szablonu przy wyborze - ostrzeżenie, nie blokada."""
        fields = self._fields()
        self.placeholders_hint.setText(
            tr(
                "settings.export.placeholders",
                names=" ".join(suggested_placeholders(enabled_fields(fields))),
            )
        )
        path = self.template_edit.text().strip()
        if not path:
            self.template_status.setText(tr("settings.export.template.builtin_hint"))
            set_props(self.template_status, role="muted", tone="")
            return None
        check = check_template(path, fields)
        if check.error is not None:
            text = tr("settings.export.template.invalid", reason=check.error)
            tone = "danger"
        elif check.unknown:
            text = tr(
                "settings.export.template.unknown",
                names=", ".join(f"{{{{{name}}}}}" for name in check.unknown),
            )
            tone = "warning"
        else:
            text = tr("settings.export.template.ok", count=len(check.placeholders))
            tone = "success"
        self.template_status.setText(text)
        set_props(self.template_status, role="status", tone=tone)
        return check


def hint_label(text: str) -> QLabel:
    """Szary opis pod polem formularza."""
    label = QLabel(text)
    label.setWordWrap(True)
    set_props(label, role="muted")
    return label


def select_data(combo: QComboBox, value: object) -> None:
    """Wybiera pozycję o danych ``value`` (nieznana - pierwsza)."""
    combo.setCurrentIndex(max(combo.findData(value), 0))


def _check(checked: bool) -> Qt.CheckState:
    return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked


def _default_label(key: str) -> str:
    return next((f.label for f in DEFAULT_FIELDS if f.key == key), key)


def _fields_spec(fields: tuple[MetadataField, ...]) -> str:
    """Zestaw domyślny zapisuje się jako pusty napis (łatwe przyszłe zmiany)."""
    return "" if fields == DEFAULT_FIELDS else encode_fields(fields)
