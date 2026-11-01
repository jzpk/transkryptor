"""Części paska narzędzi: pozycja chowana do menu, pasek z dopasowaniem
szerokości, akcje ze skrótami i przycisk menu „Więcej poleceń” (☰)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QResizeEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QMenu, QToolBar, QToolButton, QWidget

from transkryptor.i18n import tr
from transkryptor.ui import icons
from transkryptor.ui.shortcuts import set_base_tooltip
from transkryptor.ui.theme import set_props


@dataclass(frozen=True)
class Slot:
    """Pozycja paska, którą w wąskim oknie przejmuje menu „Więcej poleceń”.

    ``handles`` to uchwyty w pasku (przycisk, opis, separator); w menu trafia
    ``action`` i jej ``extras`` (polecenia z rozwijanej części przycisku).
    """

    section: str
    action: QAction
    handles: tuple[QAction, ...]
    extras: tuple[QAction | QMenu, ...] = ()

    @property
    def shown(self) -> bool:
        return self.handles[0].isVisible()

    def set_shown(self, shown: bool) -> None:
        for handle in self.handles:
            handle.setVisible(shown)


class FittingToolBar(QToolBar):
    """``QToolBar``, który po zmianie szerokości dopasowuje zestaw przycisków."""

    def __init__(self, title: str, parent: QWidget) -> None:
        super().__init__(title, parent)
        self.on_resize: Callable[[], None] = lambda: None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.on_resize()


def window_action(
    window: QMainWindow,
    label: str,
    icon: str | None,
    shortcut: str,
    tooltip: str,
    handler: Callable[[], object],
) -> QAction:
    """Akcja okna; skrót działa także dla akcji schowanej w menu przycisku."""
    action = QAction(label, window)
    if icon is not None:
        icons.set_icon(action, icon, "text", "text_muted")
    action.setShortcut(QKeySequence(shortcut))
    set_base_tooltip(action, tooltip)
    action.triggered.connect(lambda _checked=False: handler())
    window.addAction(action)
    return action


def shortcut_action(
    window: QMainWindow,
    label: str,
    icon: str | None,
    shortcut: str,
    tooltip: str,
    handler: Callable[[], object],
) -> QAction:
    """Akcja ze skrótem działającym z fokusem w edytorze."""
    action = QAction(label, window)
    if icon is not None:
        icons.set_icon(action, icon, "text", "text_muted")
    action.setShortcut(QKeySequence(shortcut))
    action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    set_base_tooltip(action, tooltip)
    action.triggered.connect(lambda _checked=False: handler())
    window.addAction(action)
    return action


def more_menu_button(window: QMainWindow) -> tuple[QMenu, QToolButton]:
    """Przycisk ☰ z menu „Więcej poleceń” (wypełnianym przy otwarciu)."""
    menu = QMenu(window)
    button = QToolButton()
    button.setObjectName("more_button")
    icons.set_icon(button, "menu", "text", "text_muted")
    button.setIconSize(icons.ICON_SIZE)
    button.setToolTip(tr("toolbar.more"))
    button.setAccessibleName(tr("toolbar.more"))
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return menu, button


def caption_label(text: str) -> QLabel:
    label = QLabel(text)
    set_props(label, role="caption")
    return label
