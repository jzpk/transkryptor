"""Powiększenie tekstu edytora niezależne od skali interfejsu.

``Ctrl`` + ``+``/``-``/``0`` i ``Ctrl`` + kółko myszy zmieniają
``EditorSettings.zoom_pct`` w krokach ``EDITOR_ZOOM_STEP_PCT``; wartość jest
zapamiętywana w ustawieniach, a edytor stosuje ją przez ``apply_settings``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from transkryptor.i18n import tr
from transkryptor.settings import EDITOR_ZOOM_RANGE_PCT, EDITOR_ZOOM_STEP_PCT
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.settings_store import SettingsStore
from transkryptor.ui.shortcuts import (
    SHORTCUT_ACTIONS_BY_ID,
    ZOOM_IN_ID,
    ZOOM_OUT_ID,
    ZOOM_RESET_ID,
)

DEFAULT_ZOOM_PCT = 100


def stepped_zoom(current: int, direction: int) -> int:
    """Powiększenie o krok w górę (``direction`` > 0) albo w dół, w zakresie."""
    low, high = EDITOR_ZOOM_RANGE_PCT
    target = current + EDITOR_ZOOM_STEP_PCT * (1 if direction > 0 else -1)
    return max(low, min(high, target))


class ZoomController(QObject):
    """Akcje powiększenia tekstu i obsługa Ctrl + kółka w edytorze."""

    def __init__(
        self,
        host: QWidget,
        editors: Iterable[TranscriptionEditor],
        settings_store: SettingsStore,
        show_status: Callable[[str], None],
    ) -> None:
        super().__init__(host)
        self._settings_store = settings_store
        self._show_status = show_status
        self.actions: dict[str, QAction] = {}
        for action_id, handler in (
            (ZOOM_IN_ID, lambda: self.step(1)),
            (ZOOM_OUT_ID, lambda: self.step(-1)),
            (ZOOM_RESET_ID, self.reset),
        ):
            action = QAction(SHORTCUT_ACTIONS_BY_ID[action_id].label, host)
            action.triggered.connect(lambda _checked=False, run=handler: run())
            host.addAction(action)
            self.actions[action_id] = action
        for editor in editors:
            editor.zoom_requested.connect(self.step)

    @property
    def zoom_pct(self) -> int:
        return self._settings_store.current.editor.zoom_pct

    def step(self, direction: int) -> None:
        self.set_zoom(stepped_zoom(self.zoom_pct, direction))

    def reset(self) -> None:
        self.set_zoom(DEFAULT_ZOOM_PCT)

    def set_zoom(self, zoom_pct: int) -> None:
        current = self._settings_store.current
        if zoom_pct != current.editor.zoom_pct:
            self._settings_store.save(
                replace(current, editor=replace(current.editor, zoom_pct=zoom_pct))
            )
        self._show_status(tr("zoom.status", zoom=zoom_pct))
