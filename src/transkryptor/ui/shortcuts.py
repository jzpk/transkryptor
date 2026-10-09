"""Skróty klawiaturowe odtwarzacza, wyszukiwania i ustawień.

Jedno źródło prawdy dla ``MainWindow`` (akcje), ``PlayerBar`` (podpowiedzi
przycisków), instrukcji i testów — wzorem ``ui/markers.py``. Skróty są stałe;
konfiguracja skrótów to osobna propozycja (21).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence

from transkryptor.i18n import tr


@dataclass(frozen=True)
class PlayerAction:
    """Akcja odtwarzacza dostępna z klawiatury przy fokusie w edytorze."""

    key: str
    label_key: str
    shortcuts: tuple[str, ...]

    @property
    def label(self) -> str:
        return tr(self.label_key)


SETTINGS_SHORTCUT = "Ctrl+,"

# Wyszukiwanie i zamiana (faza 07). Esc zamyka pasek — tylko z fokusem w pasku.
FIND_SHORTCUT = "Ctrl+F"
REPLACE_SHORTCUT = "Ctrl+H"
FIND_NEXT_SHORTCUT = "F3"
FIND_PREVIOUS_SHORTCUT = "Shift+F3"

PLAY_PAUSE = "play_pause"
SKIP_BACK = "skip_back"
SKIP_FORWARD = "skip_forward"
RATE_DOWN = "rate_down"
RATE_UP = "rate_up"
LOOP_A = "loop_a"
LOOP_B = "loop_b"
LOOP_TOGGLE = "loop_toggle"

# Ctrl+←/→ zostaje dla skoku o słowo w edytorze. F4 jest zapasowe dla
# Ctrl+Spacja, które na Linuksie bywa przechwytywane przez metodę wprowadzania.
PLAYER_ACTIONS: tuple[PlayerAction, ...] = (
    PlayerAction(PLAY_PAUSE, "player.action.play_pause", ("Ctrl+Space", "F4")),
    PlayerAction(SKIP_BACK, "player.action.skip_back", ("Alt+Left",)),
    PlayerAction(SKIP_FORWARD, "player.action.skip_forward", ("Alt+Right",)),
    PlayerAction(RATE_DOWN, "player.action.rate_down", ("Ctrl+Shift+,",)),
    PlayerAction(RATE_UP, "player.action.rate_up", ("Ctrl+Shift+.",)),
    PlayerAction(LOOP_A, "player.action.loop_a", ("Ctrl+Shift+A",)),
    PlayerAction(LOOP_B, "player.action.loop_b", ("Ctrl+Shift+B",)),
    PlayerAction(LOOP_TOGGLE, "player.action.loop_toggle", ("Ctrl+Shift+L",)),
)

PLAYER_ACTIONS_BY_KEY: dict[str, PlayerAction] = {
    action.key: action for action in PLAYER_ACTIONS
}


def native_shortcut(shortcut: str) -> str:
    """Skrót w zapisie właściwym dla systemu (np. „Ctrl+Spacja”)."""
    return QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)


def tooltip_with_shortcut(text: str, *shortcuts: str) -> str:
    """Podpowiedź z dopisanymi skrótami, np. „Odtwórz  (Ctrl+Space, F4)”."""
    if not shortcuts:
        return text
    return f"{text}  ({', '.join(native_shortcut(s) for s in shortcuts)})"


def action_tooltip(key: str, text: str | None = None) -> str:
    """Podpowiedź przycisku odtwarzacza z jego skrótami."""
    action = PLAYER_ACTIONS_BY_KEY[key]
    return tooltip_with_shortcut(text or action.label, *action.shortcuts)
