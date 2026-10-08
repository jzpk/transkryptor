"""Skróty klawiaturowe odtwarzacza, wyszukiwania i ustawień.

Jedno źródło prawdy dla ``MainWindow`` (akcje), ``PlayerBar`` (podpowiedzi
przycisków), instrukcji i testów — wzorem ``ui/markers.py``. Skróty są stałe;
konfiguracja skrótów to osobna propozycja (21).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence


@dataclass(frozen=True)
class PlayerAction:
    """Akcja odtwarzacza dostępna z klawiatury przy fokusie w edytorze."""

    key: str
    label: str
    shortcuts: tuple[str, ...]


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
    PlayerAction(PLAY_PAUSE, "Odtwórz / pauza", ("Ctrl+Space", "F4")),
    PlayerAction(SKIP_BACK, "Cofnij nagranie", ("Alt+Left",)),
    PlayerAction(SKIP_FORWARD, "Przewiń nagranie", ("Alt+Right",)),
    PlayerAction(RATE_DOWN, "Wolniej", ("Ctrl+Shift+,",)),
    PlayerAction(RATE_UP, "Szybciej", ("Ctrl+Shift+.",)),
    PlayerAction(LOOP_A, "Początek pętli (A)", ("Ctrl+Shift+A",)),
    PlayerAction(LOOP_B, "Koniec pętli (B)", ("Ctrl+Shift+B",)),
    PlayerAction(LOOP_TOGGLE, "Pętla wł./wył.", ("Ctrl+Shift+L",)),
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
