"""Testy motywu i ikon (CR-02)."""

import pytest

from transkryptor.ui import icons, theme
from transkryptor.ui.main_window import _words_label


@pytest.mark.parametrize("name", icons.available())
def test_every_icon_renders(qapp, name) -> None:
    pixmap = icons.pixmap(name, "#000000", 24, 2.0)
    assert not pixmap.toImage().isNull()
    assert pixmap.toImage().width() == 48


@pytest.mark.parametrize("tokens", [theme.LIGHT, theme.DARK])
def test_apply_theme_sets_palette_and_stylesheet(qapp, tokens) -> None:
    app = qapp
    previous_style = app.styleSheet()
    try:
        assert theme.apply_theme(app, tokens) is tokens
        assert theme.tokens() is tokens
        assert tokens.accent in app.styleSheet()
        assert app.palette().highlight().color().name().upper() == tokens.accent
    finally:
        app.setStyleSheet(previous_style)
        theme.apply_theme(app, theme.LIGHT)
        app.setStyleSheet(previous_style)


def test_theme_can_be_forced_by_environment(monkeypatch) -> None:
    monkeypatch.setenv(theme.THEME_ENV, "dark")
    assert theme.detect_tokens() is theme.DARK
    monkeypatch.setenv(theme.THEME_ENV, "light")
    assert theme.detect_tokens() is theme.LIGHT


@pytest.mark.parametrize(
    ("count", "label"),
    [(0, "słów"), (1, "słowo"), (2, "słowa"), (5, "słów"), (12, "słów"), (22, "słowa")],
)
def test_word_count_label_declension(count, label) -> None:
    assert _words_label(count) == label


def test_status_bar_and_word_count_follow_document(qtbot, add_window) -> None:
    from transkryptor.ui.main_window import STATUS_CLEAN, STATUS_DIRTY, MainWindow

    window = add_window(MainWindow())
    assert window.export_status_label.text() == STATUS_CLEAN
    assert window.word_count_label.text() == "0 słów"
    window.editor.setPlainText("bendzie uod rana")
    assert window.export_status_label.text() == STATUS_DIRTY
    assert window.word_count_label.text() == "3 słowa"
    window.document.mark_exported()
    window._update_title()
    assert window.export_status_label.text() == STATUS_CLEAN


def test_rules_summary_counts_enabled_rules(qtbot, add_window) -> None:
    from transkryptor.ui.main_window import MainWindow

    window = add_window(MainWindow())
    panel = window.asr_panel
    total = len(panel.rule_checkboxes)
    assert f"{total} z {total}" in panel.rules_toggle.text()
    next(iter(panel.rule_checkboxes.values())).setChecked(False)
    assert f"{total - 1} z {total}" in panel.rules_toggle.text()
    panel.rules_toggle.setChecked(True)
    assert not panel.rules_details.isHidden()
