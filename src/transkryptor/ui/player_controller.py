"""Sterowanie odtwarzaczem z klawiatury i z listy segmentów ASR (faza 06).

Akcje z ``ui/shortcuts.py`` są rejestrowane w oknie z kontekstem całej
aplikacji, więc działają z fokusem w edytorze. Skrót obsłużony przez akcję
nie trafia do edytora — nie wstawia znaku ani nie tworzy kroku cofania.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from transkryptor.audio.player import AudioPlayer
from transkryptor.ui.player_bar import PlayerBar
from transkryptor.ui.shortcuts import (
    LOOP_A,
    LOOP_B,
    LOOP_TOGGLE,
    PLAY_PAUSE,
    PLAYER_ACTIONS,
    RATE_DOWN,
    RATE_UP,
    SKIP_BACK,
    SKIP_FORWARD,
)


class PlayerController(QObject):
    """Akcje odtwarzacza okna i przewijanie do segmentów ASR."""

    def __init__(self, owner: QWidget, player: AudioPlayer, bar: PlayerBar) -> None:
        super().__init__(owner)
        self.player = player
        self.bar = bar
        self._locked = False
        handlers: dict[str, Callable[[], object]] = {
            PLAY_PAUSE: bar.toggle_play,
            SKIP_BACK: lambda: bar.skip(-1),
            SKIP_FORWARD: lambda: bar.skip(1),
            RATE_DOWN: lambda: bar.step_rate(-1),
            RATE_UP: lambda: bar.step_rate(1),
            LOOP_A: bar.mark_a,
            LOOP_B: bar.mark_b,
            LOOP_TOGGLE: bar.toggle_loop,
        }
        self.actions: dict[str, QAction] = {}
        for definition in PLAYER_ACTIONS:
            action = QAction(definition.label, owner)
            action.setShortcuts([QKeySequence(s) for s in definition.shortcuts])
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            handler = handlers[definition.key]
            action.triggered.connect(lambda _checked=False, run=handler: run())
            owner.addAction(action)
            self.actions[definition.key] = action
        bar.media_available_changed.connect(lambda _available: self.update_actions())
        self.update_actions()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.update_actions()

    def update_actions(self) -> None:
        """Akcje odtwarzacza: aktywne z nagraniem i poza transkrypcją ASR."""
        enabled = self.bar.has_media and not self._locked
        for action in self.actions.values():
            action.setEnabled(enabled)

    def seek_to_segment(self, position_ms: int) -> None:
        """ACC-20: odsłuch segmentu ASR od jego początku (bez auto-cofania)."""
        if self.player.source_path is None or not self.bar.has_media:
            return
        self.player.set_position(position_ms)
        self.player.play()
