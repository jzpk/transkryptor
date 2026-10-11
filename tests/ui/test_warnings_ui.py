"""Ostrzeżenia w tekście, włączanie reguł i „Ignoruj tutaj” (ACC-39, ACC-40)."""

from dataclasses import replace

from docx import Document as DocxDocument
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QFileDialog, QMenu

from transkryptor.export.docx_export import export_docx
from transkryptor.settings import ValidatorSettings, encode_bool_map
from transkryptor.ui.highlights import WARNINGS_LAYER
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog

ACC39_TEXT = "[ [dopisek] ] (?)słowo ta"


def type_text(
    window: MainWindow, text: str, superscript: tuple[int, int] | None = None
):
    window.editor.setPlainText(text)
    if superscript is not None:
        cursor = window.editor.track_range(*superscript)
        fmt = QTextCharFormat()
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
        cursor.mergeCharFormat(fmt)
    window.run_validation_now()


def underlined(window: MainWindow) -> list[tuple[int, int]]:
    return [
        window.editor.selection_range(selection.cursor)
        for selection in window.editor.highlight_layer(WARNINGS_LAYER)
    ]


class TestInlineWarnings:
    def test_acc39_problems_are_underlined_and_listed(
        self, add_window, tmp_path
    ) -> None:
        window = add_window(MainWindow())
        type_text(window, ACC39_TEXT, superscript=(24, 25))
        codes = {w.code for w in window.notation.warnings}
        assert {"VAL-06", "VAL-08", "VAL-09", "VAL-10"} <= codes
        assert window.warnings_panel.warning_count() == len(window.notation.warnings)
        ranges = underlined(window)
        assert ranges == [(w.start, w.end) for w in window.notation.warnings]
        selection = window.editor.highlight_layer(WARNINGS_LAYER)[0]
        assert (
            selection.format.underlineStyle()
            == QTextCharFormat.UnderlineStyle.WaveUnderline
        )

        # Podkreślenia należą do widoku: nie ma ich w formacie znaków ani w DOCX.
        target = tmp_path / "out.docx"
        export_docx(window.document, target)
        for run in DocxDocument(str(target)).paragraphs[-1].runs:
            assert not run.underline

    def test_tooltip_describes_warning_under_mouse(self, add_window) -> None:
        window = add_window(MainWindow())
        type_text(window, "nogie (?)dogioł")
        tooltip = window.notation.tooltip_at(7)
        assert tooltip is not None and tooltip.startswith("VAL-06")
        assert window.notation.tooltip_at(1) is None

    def test_underlines_follow_text_changes(self, add_window) -> None:
        window = add_window(MainWindow())
        type_text(window, "a  b")
        assert underlined(window) == [(1, 3)]
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(" ok")
        window.run_validation_now()
        assert underlined(window) == [(1, 3)]
        window.editor.setPlainText("a b")
        window.run_validation_now()
        assert underlined(window) == []


class TestRuleSelectionAndIgnore:
    def test_acc40_disabled_rule_and_ignored_warning_survive_project(
        self, add_window, tmp_path, monkeypatch
    ) -> None:
        window = add_window(MainWindow())
        store = window.settings_store
        store.save(
            replace(
                store.current,
                validator=ValidatorSettings(
                    overrides_spec=encode_bool_map({"VAL-07": False})
                ),
            )
        )
        type_text(window, "a  b (?)x i (?)y")
        codes = [w.code for w in window.notation.warnings]
        assert codes == ["VAL-06", "VAL-06"]

        first = window.notation.warnings[0]
        window.notation.ignore_warning(first)
        remaining = window.notation.warnings
        assert [(w.code, w.start) for w in remaining] == [("VAL-06", 12)]

        path = tmp_path / "p.transkr"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(path), "")
        )
        window.save_action.trigger()
        assert path.is_file()

        reopened = add_window(MainWindow())
        assert reopened.session.open_project(path)
        reopened.run_validation_now()
        assert [(w.code, w.start) for w in reopened.notation.warnings] == [
            ("VAL-06", 12)
        ]

    def test_context_menu_offers_ignore_here(self, add_window) -> None:
        window = add_window(MainWindow())
        type_text(window, "nogie (?)dogioł")
        menu = QMenu()
        window.notation.extend_context_menu(menu, 7)
        ignore = [a for a in menu.actions() if "VAL-06" in a.text()]
        assert len(ignore) == 1
        ignore[0].trigger()
        assert window.notation.warnings == []

    def test_panel_context_menu_ignores_warning(self, add_window) -> None:
        window = add_window(MainWindow())
        type_text(window, "nogie (?)dogioł")
        warning = window.warnings_panel.warning_at_row(0)
        assert warning is not None
        window.warnings_panel.ignore_requested.emit(warning)
        assert window.notation.warnings == []

    def test_new_document_forgets_ignored_warnings(self, add_window) -> None:
        window = add_window(MainWindow())
        type_text(window, "nogie (?)dogioł")
        window.notation.ignore_warning(window.notation.warnings[0])
        window.document.mark_exported()
        window.document.mark_saved()
        window.session.new_document()
        type_text(window, "nogie (?)dogioł")
        assert [w.code for w in window.notation.warnings] == ["VAL-06"]


class TestValidatorSettingsTab:
    def test_checkboxes_reflect_and_produce_overrides(self, qtbot) -> None:
        from transkryptor.settings import Settings

        dialog = SettingsDialog(Settings())
        qtbot.addWidget(dialog)
        assert dialog.validator_checks["VAL-07"].isChecked()
        assert not dialog.validator_checks["VAL-11"].isChecked()
        dialog.validator_checks["VAL-07"].setChecked(False)
        dialog.validator_checks["VAL-11"].setChecked(True)
        result = dialog.settings().validator
        assert result.overrides == {"VAL-07": False, "VAL-11": True}
        dialog.set_settings(Settings())
        assert dialog.settings().validator == ValidatorSettings()
