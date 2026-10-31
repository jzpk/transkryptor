"""Samouczki: przewodnik po oknie, pierwsze uruchomienie i wybór w ustawieniach."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QWidget

from transkryptor import i18n
from transkryptor.i18n import catalog
from transkryptor.settings import Settings, ShortcutSettings, TutorialSettings
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.tutorial_content import FIRST_STEPS, REVIEW, TUTORIALS


@pytest.fixture
def window(qtbot, add_window):
    window = add_window(MainWindow())
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    return window


def overlay(window: MainWindow):
    return window.tutorials.overlay


def test_every_tutorial_text_exists_in_every_language() -> None:
    for language in i18n.LANGUAGES:
        keys = set(catalog(language))
        for tutorial in TUTORIALS:
            assert f"tutorial.{tutorial.key}.title" in keys
            assert f"tutorial.{tutorial.key}.summary" in keys
            for step in tutorial.steps:
                prefix = f"tutorial.{tutorial.key}.{step.key}"
                assert f"{prefix}.title" in keys, (language, prefix)
                assert f"{prefix}.text" in keys, (language, prefix)


def test_step_texts_fill_every_shortcut_field() -> None:
    for tutorial in TUTORIALS:
        for index in range(len(tutorial.steps)):
            text = tutorial.step_text(index, lambda action: f"<{action}>")
            assert "{" not in text, (tutorial.key, tutorial.steps[index].key)


def test_every_step_points_at_a_widget_of_the_window(window) -> None:
    """Cel kroku istnieje w oknie - zmiana nazwy obiektu nie psuje samouczka."""
    for tutorial in TUTORIALS:
        for step in tutorial.steps:
            if step.targets:
                assert any(
                    window.findChild(QWidget, name) is not None for name in step.targets
                ), (tutorial.key, step.key)


def test_first_run_starts_getting_started_once(qtbot, window) -> None:
    assert window.settings_store.current.tutorial.show_on_start
    window.tutorials.start_first_run()
    assert overlay(window).isVisible()
    assert overlay(window).tutorial.key == FIRST_STEPS
    assert overlay(window).target is None  # powitanie na środku okna

    qtbot.keyClick(overlay(window), Qt.Key.Key_Escape)
    assert not overlay(window).isVisible()
    assert not window.settings_store.current.tutorial.show_on_start

    window.tutorials.start_first_run()
    assert not window.tutorials.is_running()


def test_first_run_disabled_in_settings(window) -> None:
    window.settings_store.save(
        replace(Settings(), tutorial=TutorialSettings(show_on_start=False))
    )
    window.tutorials.start_first_run()
    assert not window.tutorials.is_running()


def test_finishing_first_run_turns_it_off(window) -> None:
    window.tutorials.start_first_run()
    steps = len(overlay(window).tutorial.steps)
    for _ in range(steps):
        overlay(window).card.next_button.click()
    assert not window.tutorials.is_running()
    assert not window.settings_store.current.tutorial.show_on_start


def test_tutorial_chosen_later_keeps_the_start_setting(window) -> None:
    window.tutorials.start(REVIEW)
    overlay(window).skip()
    assert window.settings_store.current.tutorial.show_on_start


def test_navigation_highlights_widgets(qtbot, window) -> None:
    window.tutorials.start(FIRST_STEPS)
    card = overlay(window).card
    assert not card.back_button.isEnabled()
    assert "1 z 9" in card.progress_label.text()

    qtbot.keyClick(overlay(window), Qt.Key.Key_Right)
    assert overlay(window).index == 1
    assert overlay(window).target is window.player_bar
    hole = overlay(window).target_rect()
    assert hole.contains(window.player_bar.geometry().center())
    qtbot.waitUntil(lambda: card.isVisible())
    card_rect = QRect(card.pos(), card.size())
    assert not card_rect.intersects(hole)
    assert overlay(window).rect().contains(card_rect)

    qtbot.keyClick(overlay(window), Qt.Key.Key_Left)
    assert overlay(window).index == 0
    card.next_button.click()
    card.next_button.click()
    assert overlay(window).target is window.editor
    assert "Ctrl+Space / F4" in card.text_label.text()


def test_last_step_finishes(window) -> None:
    window.tutorials.start(FIRST_STEPS)
    tutorial = overlay(window).tutorial
    for _ in range(len(tutorial.steps) - 1):
        overlay(window).next()
    assert overlay(window).target is window.tutorials.button
    assert overlay(window).card.next_button.text() == "Zakończ"
    overlay(window).next()
    assert not window.tutorials.is_running()


def test_review_tutorial_reveals_the_comments_panel(qtbot, window) -> None:
    window.comments_dock.hide()
    window.tutorials.start(REVIEW)
    overlay(window).next()
    overlay(window).next()
    assert overlay(window).target is window.comments.panel
    assert window.comments_dock.isVisible()
    assert not overlay(window).target_rect().isEmpty()


def test_hidden_target_falls_back(window) -> None:
    """Przycisk weryfikacji jest widoczny dopiero z nagraniem - wtedy odtwarzacz."""
    window.tutorials.start(REVIEW)
    for _ in range(4):
        overlay(window).next()
    assert overlay(window).tutorial.steps[4].key == "verification"
    assert overlay(window).target is window.player_bar


def test_shortcut_text_follows_settings(window) -> None:
    window.settings_store.save(
        replace(
            Settings(),
            shortcuts=ShortcutSettings(overrides_spec='{"review.add_comment": []}'),
        )
    )
    assert window.tutorials.shortcut_text("review.add_comment") == (
        catalog("pl")["tutorial.no_shortcut"]
    )
    assert window.tutorials.shortcut_text("project.save") == "Ctrl+S"


def test_overlay_blocks_clicks_on_the_window(qtbot, window) -> None:
    window.tutorials.start(FIRST_STEPS)
    clicked: list[bool] = []
    window.player_bar.import_button.clicked.connect(lambda: clicked.append(True))
    point = window.player_bar.import_button.mapTo(
        window, window.player_bar.import_button.rect().center()
    )
    qtbot.mouseClick(overlay(window), Qt.MouseButton.LeftButton, pos=point)
    assert clicked == []
    assert window.tutorials.is_running()


def test_status_bar_menu_lists_every_tutorial(window) -> None:
    menu = window.tutorials.button.menu()
    keys = [action.data() for action in menu.actions()]
    assert keys == [tutorial.key for tutorial in TUTORIALS]
    menu.actions()[-1].trigger()
    assert overlay(window).tutorial.key == TUTORIALS[-1].key


def test_settings_page_round_trip(qtbot) -> None:
    dialog = SettingsDialog(
        replace(Settings(), tutorial=TutorialSettings(show_on_start=False))
    )
    qtbot.addWidget(dialog)
    page = dialog.tutorials_page
    assert not page.show_on_start_check.isChecked()
    page.show_on_start_check.setChecked(True)
    assert dialog.settings().tutorial.show_on_start
    assert page.list.count() == len(TUTORIALS)


def test_tutorial_chosen_in_settings_starts_after_closing(window, monkeypatch) -> None:
    def fake_exec(dialog: SettingsDialog) -> int:
        dialog.open_tutorials()
        dialog.tutorials_page.select(REVIEW)
        dialog.tutorials_page.start_button.click()
        return dialog.result()

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    window.settings_action.trigger()
    assert window.tutorials.is_running()
    assert overlay(window).tutorial.key == REVIEW
