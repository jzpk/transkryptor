"""Pasek narzędzi w wąskim oknie: przyciski chowają się do menu „Więcej”."""

import pytest
from PySide6.QtWidgets import QToolButton

from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.toolbar import COLLAPSE_ORDER


@pytest.fixture
def window(add_window, qtbot):
    window = add_window(MainWindow())
    window.show()
    qtbot.waitExposed(window)
    # Bez panelu ASR okno da się zwęzić do szerokości samej karty edytora.
    window.asr_dock.close()
    return window


def resize(qtbot, window: MainWindow, width: int) -> None:
    window.resize(width, 700)
    qtbot.waitUntil(lambda: window.toolbar.width() == window.width())
    # QToolBar chowa i pokazuje widżety dopiero przy kolejnym układaniu.
    qtbot.wait(20)


def menu_texts(window: MainWindow) -> list[str]:
    toolbar = window.main_toolbar
    toolbar.more_menu.aboutToShow.emit()
    return [a.text() for a in toolbar.more_menu.actions() if not a.isSeparator()]


def qt_extension_visible(window: MainWindow) -> bool:
    extension = window.toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    return extension is not None and extension.isVisible()


def test_wide_window_shows_every_button(qtbot, window) -> None:
    resize(qtbot, window, 1800)
    toolbar = window.main_toolbar
    assert toolbar.collapsed_actions() == []
    assert not toolbar.more_button.isVisible()
    assert all(not b.isHidden() for b in toolbar._buttons.values())


def test_narrow_window_moves_buttons_to_more_menu(qtbot, window) -> None:
    resize(qtbot, window, 700)
    toolbar = window.main_toolbar
    collapsed = toolbar.collapsed_actions()
    assert collapsed
    assert toolbar.more_button.isVisible()
    # Własne dopasowanie zastępuje rozszerzenie Qt — nic nie wystaje poza pasek.
    assert not qt_extension_visible(window)
    assert toolbar.toolbar.sizeHint().width() <= toolbar.toolbar.width()
    for action in collapsed:
        assert toolbar.button_for(action).isHidden()
        assert action.text() in menu_texts(window)
        # Skrót schowanego przycisku nadal działa (akcja należy do okna).
        assert action in window.actions()


def test_export_stays_and_rare_buttons_go_first(qtbot, window) -> None:
    resize(qtbot, window, 700)
    toolbar = window.main_toolbar
    assert toolbar.button_for(window.export_action).isVisible()
    collapsed = toolbar.collapsed_actions()
    assert window.updates.check_action in collapsed
    assert window.save_action not in collapsed


def test_menu_keeps_dropdown_commands(window) -> None:
    # Okno nie zwęzi się tak bardzo (karta edytora), więc zwężamy sam pasek.
    window.toolbar.resize(200, window.toolbar.height())
    texts = menu_texts(window)
    assert len(window.main_toolbar.collapsed_actions()) == len(COLLAPSE_ORDER)
    assert window.save_as_action.text() in texts
    assert window.main_toolbar.open_menu.title() in texts


def test_widening_restores_buttons(qtbot, window) -> None:
    resize(qtbot, window, 700)
    resize(qtbot, window, 1800)
    assert window.main_toolbar.collapsed_actions() == []
    assert not window.main_toolbar.more_button.isVisible()
