"""Pasek narzędzi w wąskim oknie: przyciski chowają się do menu „Więcej”."""

import pytest
from PySide6.QtWidgets import QToolButton

from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.toolbar import COLLAPSE_ORDER, NOTATION_SECTION


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


def texts_of(menu) -> list[str]:
    menu.aboutToShow.emit()
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def menu_texts(window: MainWindow) -> list[str]:
    toolbar = window.main_toolbar
    return texts_of(toolbar.notation_more_menu) + texts_of(toolbar.more_menu)


def x_of(window: MainWindow, button) -> int:
    return button.mapTo(window.toolbar, button.rect().topLeft()).x()


def qt_extension_visible(window: MainWindow) -> bool:
    extension = window.toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    return extension is not None and extension.isVisible()


def test_wide_window_shows_every_button(qtbot, window) -> None:
    resize(qtbot, window, 1800)
    toolbar = window.main_toolbar
    assert toolbar.collapsed_actions() == []
    assert not toolbar.more_button.isVisible()
    assert not toolbar.notation_more_button.isVisible()
    assert all(not b.isHidden() for b in toolbar._buttons.values())


def test_narrow_window_moves_buttons_to_more_menu(qtbot, window) -> None:
    resize(qtbot, window, 700)
    toolbar = window.main_toolbar
    collapsed = toolbar.collapsed_actions()
    assert collapsed
    assert toolbar.more_button.isVisible() or toolbar.notation_more_button.isVisible()
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
    assert toolbar._slots[COLLAPSE_ORDER[0]].action in collapsed
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
    assert not window.main_toolbar.notation_more_button.isVisible()


def test_each_group_collapses_into_menu_next_to_it(qtbot, window) -> None:
    """Znaczniki — do ☰ przed „Szkic ASR”; narzędzia i sesja — do ☰ na końcu."""
    # Narzędzia mieszczą się w najwęższym oknie (karta edytora), więc
    # zwężamy sam pasek — na stałe, żeby układ okna go nie rozszerzył.
    window.toolbar.setMaximumWidth(400)
    qtbot.waitUntil(lambda: window.toolbar.width() <= 400)
    qtbot.wait(20)
    toolbar = window.main_toolbar
    slots = toolbar._slots.values()
    notation = [s.action for s in slots if s.section == NOTATION_SECTION]
    collapsed = toolbar.collapsed_actions()
    hidden_notation = [a for a in collapsed if a in notation]
    hidden_tools = [a for a in collapsed if a not in notation]
    assert hidden_notation and hidden_tools  # oba menu w użyciu

    assert toolbar.notation_more_button.isVisible()
    assert texts_of(toolbar.notation_more_menu) == [a.text() for a in hidden_notation]
    assert texts_of(toolbar.more_menu)[: len(hidden_tools)] == [
        a.text() for a in hidden_tools
    ]
    # ☰ notacji stoi za ostatnim widocznym znacznikiem, a przed przyciskami
    # z prawej strony paska; ☰ narzędzi — na samym końcu.
    visible_right = [
        toolbar.button_for(a)
        for a in (window.asr_panel_action, window.export_action)
        if toolbar.button_for(a).isVisible()
    ]
    notation_x = x_of(window, toolbar.notation_more_button)
    assert all(notation_x < x_of(window, b) for b in visible_right)
    assert all(
        x_of(window, toolbar.button_for(a)) < notation_x
        for a in notation
        if a not in collapsed
    )
    assert all(
        x_of(window, b) < x_of(window, toolbar.more_button) for b in visible_right
    )


def test_first_collapsed_marker_goes_to_notation_menu(qtbot, window) -> None:
    """Pierwszy schowany znacznik nie trafia do ☰ na końcu paska."""
    toolbar = window.main_toolbar
    first_marker = next(k for k in COLLAPSE_ORDER if k.startswith("marker:"))
    marker = toolbar._slots[first_marker].action
    for width in range(1800, 600, -10):
        resize(qtbot, window, width)
        if marker in toolbar.collapsed_actions():
            break
    else:
        pytest.fail("znacznik nie schował się nawet w wąskim oknie")
    assert marker.text() in texts_of(toolbar.notation_more_menu)
    assert marker.text() not in texts_of(toolbar.more_menu)
    assert toolbar.notation_more_button.isVisible()
