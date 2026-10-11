"""Reguły fonetyczne użytkownika w UI: edytor, panel ASR, błędy (ACC-41, ACC-42)."""

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from transkryptor.settings import Settings
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog

SLOW_AND_BROKEN = """
[[rule]]
code = "USR-BROKEN"
label = "Zepsuta"
pattern = '(ą'
replacement = 'o'
confidence = 0.3

[[rule]]
code = "USR-SLOW"
label = "Wolna"
pattern = '(a|aa)+$'
replacement = 'x'
confidence = 0.3

[[rule]]
code = "USR-CH"
label = "Własna: ch → h"
pattern = 'ch$'
replacement = 'h'
confidence = 0.6
"""


def fill_rule(dialog: SettingsDialog, **fields: str) -> None:
    """Wpisuje pola formularza bieżącej reguły (jak użytkownik)."""
    editor = dialog.rules_editor
    widgets = {
        "code": editor.code_edit,
        "label": editor.label_edit,
        "pattern": editor.pattern_edit,
        "replacement": editor.replacement_edit,
        "example": editor.example_edit,
    }
    for name, value in fields.items():
        widget = widgets[name]
        widget.setText(value)
        widget.textEdited.emit(value)


def accept(window: MainWindow, dialog: SettingsDialog) -> None:
    dialog.accept()
    assert dialog.result() == SettingsDialog.DialogCode.Accepted
    window.accept_settings_dialog(dialog)


class TestRulesEditor:
    def test_acc41_rule_from_editor_reaches_asr_and_survives_restart(
        self, add_window, isolated_rules
    ) -> None:
        window = add_window(MainWindow())
        window.editor.setPlainText("tych som")
        dialog = window.create_settings_dialog()
        dialog.rules_editor.add_rule()
        fill_rule(
            dialog,
            code="USR-SOM",
            label="Moja reguła",
            pattern="o(?=m$)",
            replacement="ó",
            example="som",
        )
        editor = dialog.rules_editor
        assert "s<b>ó</b>m" in editor.preview_label.text()
        assert "1" in editor.matches_label.text()
        editor.confidence_spin.setValue(0.7)
        accept(window, dialog)
        assert isolated_rules.is_file()

        boxes = window.asr_panel.rule_checkboxes
        assert "USR-SOM" in boxes and "70%" in boxes["USR-SOM"].text()
        assert not boxes["USR-SOM"].isChecked()
        boxes["USR-SOM"].setChecked(True)
        window.editor.clear()
        window._on_draft_ready("som")
        assert window.editor.toPlainText() == "sóm"
        assert any(item.suggestion.code == "USR-SOM" for item in window.review.items)

        restarted = add_window(MainWindow())
        assert "USR-SOM" in restarted.asr_panel.rule_checkboxes

    def test_builtin_rules_are_read_only(self, qtbot) -> None:
        from transkryptor.notation.rules import builtin_rules

        dialog = SettingsDialog(Settings(), builtin_rules=builtin_rules().rules)
        qtbot.addWidget(dialog)
        editor = dialog.rules_editor
        editor.rule_list.setCurrentRow(0)
        assert not editor.pattern_edit.isEnabled()
        assert not editor.remove_button.isEnabled()
        assert "<sup><b>m</b></sup>" in editor.preview_label.text()

    def test_invalid_rule_blocks_accept(self, qtbot, monkeypatch) -> None:
        warnings: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning", lambda _p, _t, text, *a, **k: warnings.append(text)
        )
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        dialog.rules_editor.add_rule()
        fill_rule(dialog, pattern="(", replacement="x")
        assert dialog.rules_editor.error_label.text()
        dialog.accept()
        assert dialog.result() != SettingsDialog.DialogCode.Accepted
        assert warnings and "USR-1" in warnings[0]
        assert dialog.tabs.currentWidget() is dialog.rules_editor

    def test_export_and_import_rule_set(self, qtbot, tmp_path: Path) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        editor = dialog.rules_editor
        editor.add_rule()
        fill_rule(dialog, label="Eksport", pattern="ch$", replacement="h")
        target = tmp_path / "zestaw.toml"
        editor.export_rules_to(target)

        other = SettingsDialog(Settings())
        qtbot.addWidget(other)
        count, errors = other.rules_editor.import_rules_from(target)
        assert (count, errors) == (1, [])
        assert other.user_rules() == editor.user_rules()
        # Ten sam kod drugi raz to błąd z kodem reguły, nie duplikat.
        count, errors = other.rules_editor.import_rules_from(target)
        assert count == 0 and "USR-1" in errors[0]

    def test_remove_rule(self, qtbot) -> None:
        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        dialog.rules_editor.add_rule()
        dialog.rules_editor.remove_rule()
        assert dialog.user_rules() == ()


class TestBrokenRulesFile:
    def test_acc42_app_starts_reports_errors_and_slow_rule_does_not_block(
        self, add_window, isolated_rules, no_blocking_dialogs
    ) -> None:
        isolated_rules.parent.mkdir(parents=True)
        isolated_rules.write_text(SLOW_AND_BROKEN, encoding="utf-8")
        window = add_window(MainWindow())
        assert [r.code for r in window.rules_store.user_rules] == [
            "USR-SLOW",
            "USR-CH",
        ]
        window.report_rule_errors()
        kind, _title, text = no_blocking_dialogs[-1]
        assert kind == "warning" and "USR-BROKEN" in text and "pattern" in text

        window.editor.clear()
        window._on_draft_ready(("a" * 40 + "b ") * 20 + "tych")
        codes = {item.suggestion.code for item in window.review.items}
        assert "USR-CH" in codes and "USR-SLOW" not in codes
        kind, _title, text = no_blocking_dialogs[-1]
        assert kind == "warning" and "USR-SLOW" in text

    def test_no_message_without_errors(self, add_window, no_blocking_dialogs) -> None:
        window = add_window(MainWindow())
        window.report_rule_errors()
        assert no_blocking_dialogs == []
