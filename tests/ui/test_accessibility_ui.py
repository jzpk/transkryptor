"""Dostępność: powiększenie tekstu, skala, wysoki kontrast, czytniki ekranu."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QToolButton

from transkryptor import __main__ as entry
from transkryptor.i18n import tr
from transkryptor.notation.validator import SEVERITY_HINT, SEVERITY_WARNING
from transkryptor.settings import (
    AppearanceSettings,
    EditorSettings,
    Settings,
)
from transkryptor.ui import accessibility
from transkryptor.ui.highlights import WARNINGS_LAYER
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_store import SettingsStore
from transkryptor.ui.shortcuts import ZOOM_IN_ID, ZOOM_OUT_ID, ZOOM_RESET_ID
from transkryptor.ui.theme import HIGH_CONTRAST, resolve_tokens, tokens
from transkryptor.ui.tutorial_content import TUTORIALS_BY_KEY
from transkryptor.ui.zoom_controller import stepped_zoom


@pytest.fixture
def window(add_window) -> MainWindow:
    return add_window(MainWindow())


def wheel(widget, delta: int, modifiers=Qt.KeyboardModifier.ControlModifier):
    return QWheelEvent(
        QPointF(10, 10),
        QPointF(widget.mapToGlobal(QPoint(10, 10))),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


class TestEditorZoom:
    def test_shortcuts_change_and_remember_zoom(self, window) -> None:
        base = window.editor.font().pointSizeF()
        window.zoom.actions[ZOOM_IN_ID].trigger()
        window.zoom.actions[ZOOM_IN_ID].trigger()
        assert window.settings_store.current.editor.zoom_pct == 120
        assert window.editor.font().pointSizeF() == pytest.approx(base * 1.2)
        assert window.compare_view.font().pointSizeF() == pytest.approx(base * 1.2)
        assert "120%" in window.statusBar().currentMessage()
        assert SettingsStore().load().editor.zoom_pct == 120
        window.zoom.actions[ZOOM_OUT_ID].trigger()
        assert window.settings_store.current.editor.zoom_pct == 110
        window.zoom.actions[ZOOM_RESET_ID].trigger()
        assert window.editor.font().pointSizeF() == pytest.approx(base)

    def test_default_shortcuts(self, window) -> None:
        shortcuts = [
            s.toString() for s in window.shortcut_actions[ZOOM_IN_ID].shortcuts()
        ]
        assert shortcuts == ["Ctrl++", "Ctrl+="]
        assert window.shortcut_actions[ZOOM_RESET_ID].shortcut().toString() == (
            "Ctrl+0"
        )

    def test_ctrl_wheel_zooms_without_scrolling(self, window) -> None:
        QApplication.sendEvent(window.editor.viewport(), wheel(window.editor, 120))
        assert window.settings_store.current.editor.zoom_pct == 110
        QApplication.sendEvent(window.editor.viewport(), wheel(window.editor, -120))
        QApplication.sendEvent(window.editor.viewport(), wheel(window.editor, -120))
        assert window.settings_store.current.editor.zoom_pct == 90

    def test_plain_wheel_does_not_zoom(self, window) -> None:
        event = wheel(window.editor, 120, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(window.editor.viewport(), event)
        assert window.settings_store.current.editor.zoom_pct == 100

    def test_zoom_stays_in_range(self) -> None:
        assert stepped_zoom(300, 1) == 300
        assert stepped_zoom(50, -1) == 50
        assert stepped_zoom(100, 1) == 110

    def test_zoom_scales_explicit_font_size(self, window) -> None:
        window.editor.apply_settings(EditorSettings(font_size_pt=12, zoom_pct=150))
        assert window.editor.font().pointSizeF() == pytest.approx(18)


class TestAppearance:
    def test_page_saves_scale_motion_and_theme(self, window) -> None:
        dialog = window.create_settings_dialog()
        page = dialog.appearance_page
        assert page.ui_scale_hint.isHidden()
        page.ui_scale_spin.setValue(150)
        assert not page.ui_scale_hint.isHidden()
        page.reduce_motion_check.setChecked(True)
        page.theme_combo.setCurrentIndex(page.theme_combo.findData("high_contrast"))
        page.zoom_spin.setValue(130)
        assert "Ctrl++" in page.zoom_hint.text()
        settings = dialog.settings()
        assert settings.appearance == AppearanceSettings(
            theme="high_contrast", ui_scale_pct=150, reduce_motion=True
        )
        assert settings.editor.zoom_pct == 130

    def test_high_contrast_theme_applies(self, window) -> None:
        assert resolve_tokens("high_contrast") is HIGH_CONTRAST
        current = window.settings_store.current
        window.settings_store.save(
            replace(
                current,
                appearance=replace(current.appearance, theme="high_contrast"),
            )
        )
        assert tokens() is HIGH_CONTRAST
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        assert "#FFD700" in app.styleSheet()
        window.settings_store.save(current)

    def test_ui_scale_is_set_before_start(self, isolated_settings) -> None:
        store = SettingsStore(isolated_settings())
        store.save(Settings(appearance=AppearanceSettings(ui_scale_pct=150)))
        environ: dict[str, str] = {}
        assert entry.configure_ui_scale(isolated_settings(), environ) == 1.5
        assert environ == {"QT_SCALE_FACTOR": "1.5"}

    def test_ui_scale_respects_system_variable(self, isolated_settings) -> None:
        store = SettingsStore(isolated_settings())
        store.save(Settings(appearance=AppearanceSettings(ui_scale_pct=200)))
        environ = {"QT_SCALE_FACTOR": "1.25"}
        entry.configure_ui_scale(isolated_settings(), environ)
        assert environ == {"QT_SCALE_FACTOR": "1.25"}

    def test_default_scale_leaves_environment(self, isolated_settings) -> None:
        environ: dict[str, str] = {}
        assert entry.configure_ui_scale(isolated_settings(), environ) == 1.0
        assert environ == {}

    def test_reduced_motion_stops_tutorial_pulse(self, window) -> None:
        window.tutorials.start("basics")
        assert window.tutorials.overlay.is_pulsing()
        window.tutorials.overlay.skip()
        current = window.settings_store.current
        window.settings_store.save(
            replace(current, appearance=replace(current.appearance, reduce_motion=True))
        )
        window.tutorials.start("basics")
        assert not window.tutorials.overlay.is_pulsing()
        window.tutorials.overlay.skip()


class TestDistinguishableWithoutColour:
    def test_hints_and_warnings_use_different_underlines(self, window) -> None:
        # VAL-05 (wskazówka: wielokropek ASCII) i VAL-02 (ostrzeżenie: nawias).
        window.editor.setPlainText("tak... [a")
        window.run_validation_now()
        severities = {warning.severity for warning in window.notation.warnings}
        assert severities == {SEVERITY_HINT, SEVERITY_WARNING}
        styles = {
            selection.format.underlineStyle()
            for selection in window.editor.highlight_layer(WARNINGS_LAYER)
        }
        assert len(styles) == 2


class TestScreenReaders:
    def test_buttons_have_accessible_names(self, window) -> None:
        unnamed = [
            button.objectName() or button.toolTip()
            for button in window.findChildren(QToolButton)
            if button.isVisibleTo(window)
            and not button.accessibleName()
            and (button.text() or button.toolTip())
        ]
        assert unnamed == []

    def test_main_lists_and_fields_are_named(self, window) -> None:
        assert window.warnings_panel.accessibleName() == tr("main.warnings")
        assert window.warnings_panel.accessibleDescription()
        assert window.comments.panel.tree.accessibleName()
        assert window.author_edit.accessibleName()
        assert window.date_edit.accessibleName()
        assert all(
            edit.accessibleName() for edit in window.metadata_form.edits.values()
        )

    def test_status_messages_are_announced(self, window, monkeypatch) -> None:
        announced: list[str] = []
        monkeypatch.setattr(
            accessibility, "announce", lambda _widget, text: announced.append(text)
        )
        window.show_status("Zapisano projekt")
        assert announced == ["Zapisano projekt"]

    def test_plain_label_strips_shortcuts_and_accelerators(self) -> None:
        assert accessibility.plain_label("&Zapisz  (Ctrl+S)") == "Zapisz"
        assert accessibility.plain_label("A && B\ndruga linia") == "A & B"


def test_comfort_tutorial_points_at_profile_switcher(window) -> None:
    tutorial = TUTORIALS_BY_KEY["comfort"]
    assert tutorial.steps[0].targets == ("profile_switcher",)
    text = tutorial.step_text(2, window.tutorials.shortcut_text)
    assert "Ctrl++" in text
