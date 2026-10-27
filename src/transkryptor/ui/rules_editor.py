"""Zakładka „Reguły fonetyczne” okna ustawień (propozycja 11).

Lista reguł wbudowanych (tylko do odczytu) i reguł użytkownika, formularz
reguły, podgląd działania na przykładzie i liczba dopasowań w bieżącym
tekście oraz eksport i import zestawu reguł do pliku ``.toml``. Edytor
zmienia tylko kopię reguł; zapis wykonuje okno główne po zatwierdzeniu
ustawień (``RulesStore``).
"""

from __future__ import annotations

import html
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from transkryptor.errors import AppError
from transkryptor.fileio import write_atomic
from transkryptor.i18n import tr
from transkryptor.notation.learning import free_code
from transkryptor.notation.rules import (
    ANY_LANGUAGE,
    SCOPE_PAIR,
    SCOPE_WORD,
    USER_PREFIX,
    PhoneticRule,
    check_rule,
    dumps_rules,
    localized,
)
from transkryptor.notation.suggestions import (
    Suggestion,
    propose_with_report,
    without_overlaps,
)
from transkryptor.ui.messages import show_error
from transkryptor.ui.rules_store import read_rules_file
from transkryptor.ui.theme import set_props, tokens

DEFAULT_CONFIDENCE = 0.3


class RulesEditor(QWidget):
    """Edycja reguł użytkownika z podglądem; wbudowane tylko do podglądu."""

    def __init__(
        self,
        builtin: tuple[PhoneticRule, ...],
        user: tuple[PhoneticRule, ...],
        document_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._builtin = builtin
        self._user: list[PhoneticRule] = list(user)
        self._document_text = document_text
        self._loading = False

        hint = QLabel(tr("settings.rules.hint", prefix=USER_PREFIX))
        hint.setWordWrap(True)
        set_props(hint, role="muted")

        self.rule_list = QListWidget()
        self.rule_list.setMinimumHeight(110)
        self.rule_list.setWordWrap(True)
        self.rule_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.rule_list.currentRowChanged.connect(self._on_row_changed)

        self.code_edit = QLineEdit()
        self.label_edit = QLineEdit()
        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("(?<=.)ą$")
        self.scope_combo = QComboBox()
        self.scope_combo.addItem(tr("settings.rules.scope.word"), SCOPE_WORD)
        self.scope_combo.addItem(tr("settings.rules.scope.pair"), SCOPE_PAIR)
        self.replacement_edit = QLineEdit()
        self.replacement_edit.setPlaceholderText("o^m")
        self.replacement_edit.setToolTip(tr("settings.rules.replacement.tooltip"))
        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.05, 1.0)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setDecimals(2)
        self.auto_check = QCheckBox(tr("settings.rules.auto_apply"))
        self.example_edit = QLineEdit()
        self.description_edit = QLineEdit()
        for edit in (
            self.code_edit,
            self.label_edit,
            self.pattern_edit,
            self.replacement_edit,
            self.example_edit,
            self.description_edit,
        ):
            edit.textEdited.connect(self._on_form_changed)
        self.scope_combo.currentIndexChanged.connect(self._on_form_changed)
        self.confidence_spin.valueChanged.connect(self._on_form_changed)
        self.auto_check.toggled.connect(self._on_form_changed)

        form = QFormLayout()
        form.addRow(tr("settings.rules.code"), self.code_edit)
        form.addRow(tr("settings.rules.label"), self.label_edit)
        form.addRow(tr("settings.rules.pattern"), self.pattern_edit)
        form.addRow(tr("settings.rules.scope"), self.scope_combo)
        form.addRow(tr("settings.rules.replacement"), self.replacement_edit)
        form.addRow(tr("settings.rules.confidence"), self.confidence_spin)
        form.addRow(self.auto_check)
        form.addRow(tr("settings.rules.example"), self.example_edit)
        form.addRow(tr("settings.rules.description"), self.description_edit)
        self._form_widgets: tuple[QWidget, ...] = (
            self.code_edit,
            self.label_edit,
            self.pattern_edit,
            self.scope_combo,
            self.replacement_edit,
            self.confidence_spin,
            self.auto_check,
            self.example_edit,
            self.description_edit,
        )

        self.preview_label = QLabel()
        self.preview_label.setTextFormat(Qt.TextFormat.RichText)
        self.preview_label.setWordWrap(True)
        self.matches_label = QLabel()
        set_props(self.matches_label, role="muted")
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        set_props(self.error_label, tone="warning")

        self.add_button = QPushButton(tr("settings.rules.add"))
        self.remove_button = QPushButton(tr("settings.rules.remove"))
        self.import_button = QPushButton(tr("settings.rules.import"))
        self.export_button = QPushButton(tr("settings.rules.export"))
        self.add_button.clicked.connect(self.add_rule)
        self.remove_button.clicked.connect(self.remove_rule)
        self.import_button.clicked.connect(self._on_import)
        self.export_button.clicked.connect(self._on_export)
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.remove_button,
            self.import_button,
            self.export_button,
        ):
            buttons.addWidget(button)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 8, 0)
        details_layout.addLayout(form)
        details_layout.addStretch(1)
        # Formularz przewija się w niskim oknie zamiast ściskać pola.
        scroll = QScrollArea()
        scroll.setWidget(details)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(hint)
        layout.addWidget(self.rule_list, stretch=1)
        layout.addLayout(buttons)
        # Podgląd nad formularzem - widoczny bez przewijania.
        layout.addWidget(self.preview_label)
        layout.addWidget(self.matches_label)
        layout.addWidget(self.error_label)
        layout.addWidget(scroll, stretch=2)

        self._refresh_list()
        self.rule_list.setCurrentRow(0 if self.rule_list.count() else -1)

    # --- dane ---------------------------------------------------------------

    def user_rules(self) -> tuple[PhoneticRule, ...]:
        return tuple(self._user)

    def first_problem(self) -> str | None:
        """Opis pierwszej błędnej reguły użytkownika (blokuje zapis) albo None."""
        for index, rule in enumerate(self._user):
            problem = check_rule(rule, self._taken_codes(index))
            if problem is not None:
                return tr(
                    "settings.rules.invalid", code=rule.code or "?", problem=problem
                )
        return None

    def select_user_rule(self, index: int) -> None:
        self.rule_list.setCurrentRow(len(self._builtin) + index)

    def add_rule(self) -> None:
        """Nowa reguła użytkownika z wolnym kodem ``USR-n``."""
        self._user.append(
            PhoneticRule(
                code=free_code(self._taken_codes()),
                label={ANY_LANGUAGE: tr("settings.rules.new_label")},
                pattern="",
                replacement="",
                confidence=DEFAULT_CONFIDENCE,
            )
        )
        self._refresh_list()
        self.select_user_rule(len(self._user) - 1)
        self.pattern_edit.setFocus()

    def add_proposed_rule(self, rule: PhoneticRule) -> None:
        """Dopisuje gotową regułę (np. z poprawek) z wolnym kodem i ją zaznacza."""
        taken = self._taken_codes()
        if rule.code in taken:
            rule = replace(rule, code=free_code(taken))
        self._user.append(rule)
        self._refresh_list()
        self.select_user_rule(len(self._user) - 1)
        self.pattern_edit.setFocus()

    def remove_rule(self) -> None:
        index = self._user_index()
        if index is None:
            return
        del self._user[index]
        self._refresh_list()
        if self._user:
            self.select_user_rule(min(index, len(self._user) - 1))
        else:
            self.rule_list.setCurrentRow(0 if self.rule_list.count() else -1)

    def import_rules_from(self, path: Path) -> tuple[int, list[str]]:
        """Dopisuje reguły z pliku; zwraca liczbę dodanych i opisy błędów."""
        loaded = read_rules_file(path, self._taken_codes())
        self._user.extend(loaded.rules)
        self._refresh_list()
        if loaded.rules:
            self.select_user_rule(len(self._user) - 1)
        return len(loaded.rules), [error.message for error in loaded.errors]

    def export_rules_to(self, path: Path) -> None:
        write_atomic(path, dumps_rules(self._user).encode("utf-8"))

    # --- lista i formularz --------------------------------------------------

    def _taken_codes(self, skip_user: int | None = None) -> set[str]:
        codes = {rule.code for rule in self._builtin}
        codes.update(rule.code for i, rule in enumerate(self._user) if i != skip_user)
        return codes

    def _all_rules(self) -> list[PhoneticRule]:
        return [*self._builtin, *self._user]

    def _user_index(self) -> int | None:
        row = self.rule_list.currentRow() - len(self._builtin)
        return row if 0 <= row < len(self._user) else None

    def _current_rule(self) -> PhoneticRule | None:
        row = self.rule_list.currentRow()
        rules = self._all_rules()
        return rules[row] if 0 <= row < len(rules) else None

    def _refresh_list(self) -> None:
        row = self.rule_list.currentRow()
        self.rule_list.blockSignals(True)
        self.rule_list.clear()
        for rule in self._all_rules():
            text = f"{rule.code} - {rule.label_text}"
            if rule.builtin:
                text = tr("settings.rules.builtin_item", rule=text)
            item = QListWidgetItem(text)
            if rule.builtin:
                set_item_muted(item)
            self.rule_list.addItem(item)
        self.rule_list.blockSignals(False)
        if 0 <= row < self.rule_list.count():
            self.rule_list.setCurrentRow(row)

    def _on_row_changed(self, _row: int) -> None:
        rule = self._current_rule()
        editable = rule is not None and not rule.builtin
        self._loading = True
        for widget in self._form_widgets:
            widget.setEnabled(editable)
        self.remove_button.setEnabled(editable)
        self.code_edit.setText(rule.code if rule else "")
        self.label_edit.setText(rule.label_text if rule else "")
        self.pattern_edit.setText(rule.pattern if rule else "")
        self.scope_combo.setCurrentIndex(
            max(self.scope_combo.findData(rule.scope if rule else SCOPE_WORD), 0)
        )
        self.replacement_edit.setText(rule.replacement if rule else "")
        self.confidence_spin.setValue(rule.confidence if rule else DEFAULT_CONFIDENCE)
        self.auto_check.setChecked(rule.auto_apply if rule else False)
        self.example_edit.setText(rule.example if rule else "")
        self.description_edit.setText(
            localized(rule.description) if rule and rule.description else ""
        )
        self._loading = False
        self._update_preview()

    def _on_form_changed(self, *_args: object) -> None:
        if self._loading:
            return
        index = self._user_index()
        if index is None:
            return
        description = self.description_edit.text().strip()
        self._user[index] = PhoneticRule(
            code=self.code_edit.text().strip(),
            label={ANY_LANGUAGE: self.label_edit.text().strip()},
            pattern=self.pattern_edit.text(),
            replacement=self.replacement_edit.text(),
            confidence=round(self.confidence_spin.value(), 2),
            scope=str(self.scope_combo.currentData()),
            description={ANY_LANGUAGE: description} if description else {},
            example=self.example_edit.text(),
            auto_apply=self.auto_check.isChecked(),
        )
        item = self.rule_list.item(self.rule_list.currentRow())
        if item is not None:
            rule = self._user[index]
            item.setText(f"{rule.code} - {rule.label_text}")
        self._update_preview()

    def _update_preview(self) -> None:
        rule = self._current_rule()
        if rule is None:
            self.preview_label.clear()
            self.matches_label.clear()
            self.error_label.clear()
            return
        index = self._user_index()
        problem = None if rule.builtin else check_rule(rule, self._taken_codes(index))
        self.error_label.setText(problem or "")
        try:
            example = (
                propose_with_report(rule.example, [rule]) if rule.example else None
            )
            in_text = propose_with_report(self._document_text, [rule])
        except ValueError:
            self.preview_label.setText(tr("settings.rules.preview.none"))
            self.matches_label.clear()
            return
        if example is None:
            self.preview_label.setText(tr("settings.rules.preview.no_example"))
        elif example.failed:
            self.preview_label.setText(tr("settings.rules.preview.too_slow"))
        else:
            self.preview_label.setText(
                tr(
                    "settings.rules.preview",
                    example=html.escape(rule.example),
                    result=preview_html(rule.example, example.suggestions),
                )
            )
        if in_text.failed:
            self.matches_label.setText(tr("settings.rules.preview.too_slow"))
        else:
            self.matches_label.setText(
                tr("settings.rules.matches", count=len(in_text.suggestions))
            )

    # --- pliki --------------------------------------------------------------

    def _on_import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("settings.rules.import"), "", tr("settings.rules.file_filter")
        )
        if not path:
            return
        count, errors = self.import_rules_from(Path(path))
        text = tr("settings.rules.imported", count=count)
        if errors:
            QMessageBox.warning(
                self, tr("settings.rules.import"), text + "\n\n" + "\n".join(errors)
            )
        else:
            QMessageBox.information(self, tr("settings.rules.import"), text)

    def _on_export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("settings.rules.export"), "", tr("settings.rules.file_filter")
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".toml")
        try:
            self.export_rules_to(target)
        except AppError as error:
            show_error(self, tr("settings.rules.export"), error)


def preview_html(text: str, suggestions: list[Suggestion]) -> str:
    """Tekst po zastosowaniu propozycji, indeks górny jako ``<sup>``."""
    chunks: list[str] = []
    position = 0
    for suggestion in without_overlaps(suggestions):
        chunks.append(html.escape(text[position : suggestion.start]))
        replacement = suggestion.replacement
        cursor = 0
        for start, end in suggestion.superscript_ranges:
            chunks.append(f"<b>{html.escape(replacement[cursor:start])}</b>")
            chunks.append(f"<sup><b>{html.escape(replacement[start:end])}</b></sup>")
            cursor = end
        chunks.append(f"<b>{html.escape(replacement[cursor:])}</b>")
        position = suggestion.end
    chunks.append(html.escape(text[position:]))
    return "".join(chunks)


def set_item_muted(item: QListWidgetItem) -> None:
    item.setForeground(QColor(tokens().text_muted))
