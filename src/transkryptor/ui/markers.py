"""Definicje markerów notacji i skrótów klawiaturowych edytora.

Jedno źródło prawdy dla przycisków paska narzędzi, skrótów oraz testów UI.
Teksty wstawiane do dokumentu pochodzą z ``specs/transcription-rules.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence

from transkryptor.notation.ellipsis import EllipsisStyle, pause_text


@dataclass(frozen=True)
class MarkerAction:
    """Akcja edytora: wstawienie markera lub przełączenie formatowania."""

    key: str
    label: str
    inserted_text: str
    shortcut: str


SUPERSCRIPT_SHORTCUT = "Ctrl+Shift+Up"

# Pauza w zapisie trzech kropek; tekst wstawiany przez narzędzie zależy od
# ustawienia stylu wielokropka — zob. ``marker_text``.
PAUSE_TEXT = pause_text(EllipsisStyle.ASCII)
ODDITY_TEXT = "(!)"
DOUBT_TEXT = "(?)"
OMITTED_TEXT = "[…?]"
ASIDE_TEXT = "[...]"  # stała postać, niezależna od stylu wielokropka

MARKERS: tuple[MarkerAction, ...] = (
    MarkerAction(
        key="pause",
        label="Pauza",
        inserted_text=PAUSE_TEXT,
        shortcut="Ctrl+.",
    ),
    MarkerAction(
        key="oddity",
        label="Osobliwość (!)",
        inserted_text=ODDITY_TEXT,
        shortcut="Ctrl+1",
    ),
    MarkerAction(
        key="doubt",
        label="Wątpliwość (?)",
        inserted_text=DOUBT_TEXT,
        shortcut="Ctrl+2",
    ),
    MarkerAction(
        key="omitted",
        label="Pominięty […?]",
        inserted_text=OMITTED_TEXT,
        shortcut="Ctrl+3",
    ),
    MarkerAction(
        key="aside",
        label="Dopisek [...]",
        inserted_text=ASIDE_TEXT,
        shortcut="Ctrl+[",
    ),
)


MARKERS_BY_KEY: dict[str, MarkerAction] = {marker.key: marker for marker in MARKERS}


def marker_text(key: str, style: EllipsisStyle) -> str:
    """Tekst wstawiany przez marker przy danym stylu wielokropka (ACC-03)."""
    if key == "pause":
        return pause_text(style)
    return MARKERS_BY_KEY[key].inserted_text


def key_sequence(shortcut: str) -> QKeySequence:
    """Zwraca QKeySequence dla skrótu z definicji markera."""
    return QKeySequence(shortcut)
