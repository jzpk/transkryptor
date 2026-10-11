"""Warstwy podświetleń edytora (``ExtraSelections``) w ustalonej kolejności.

Podświetlenia należą do widoku, nie do dokumentu: nie są formatem znaków,
nie trafiają do ``Document``, pliku projektu ani eksportu DOCX. Każdy
kontroler zarządza własną warstwą, a edytor składa je w kolejności
``LAYER_ORDER`` — późniejsza warstwa jest rysowana na wierzchu.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit

# Od spodu: aktywny segment odtwarzania (tło), niepewne słowa ASR i ostrzeżenia
# (podkreślenia), przegląd ASR, wyszukiwanie na wierzchu.
ACTIVE_LAYER = "active"
UNCERTAIN_LAYER = "uncertain"
WARNINGS_LAYER = "warnings"
REVIEW_LAYER = "review"
SEARCH_LAYER = "search"
LAYER_ORDER = (
    ACTIVE_LAYER,
    UNCERTAIN_LAYER,
    WARNINGS_LAYER,
    REVIEW_LAYER,
    SEARCH_LAYER,
)


class HighlightLayers:
    """Podświetlenia pogrupowane w nazwane warstwy."""

    def __init__(self) -> None:
        self._layers: dict[str, list[QTextEdit.ExtraSelection]] = {}

    def set(self, name: str, selections: list[QTextEdit.ExtraSelection]) -> None:
        if name not in LAYER_ORDER:
            raise ValueError(f"Nieznana warstwa podświetleń: {name}")
        self._layers[name] = list(selections)

    def get(self, name: str) -> list[QTextEdit.ExtraSelection]:
        return list(self._layers.get(name, []))

    def ordered(self) -> list[QTextEdit.ExtraSelection]:
        """Wszystkie podświetlenia w kolejności rysowania."""
        return [
            selection
            for layer in LAYER_ORDER
            for selection in self._layers.get(layer, [])
        ]


def background(cursor: QTextCursor, color: QColor) -> QTextEdit.ExtraSelection:
    """Podświetlenie zakresu kursora tłem."""
    selection = QTextEdit.ExtraSelection()
    selection.cursor = cursor
    selection.format.setBackground(color)
    return selection


def wave_underline(cursor: QTextCursor, color: QColor) -> QTextEdit.ExtraSelection:
    """Faliste podkreślenie zakresu (jak w korektorze pisowni)."""
    selection = QTextEdit.ExtraSelection()
    selection.cursor = cursor
    selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
    selection.format.setUnderlineColor(color)
    return selection


def dotted_underline(cursor: QTextCursor, color: QColor) -> QTextEdit.ExtraSelection:
    """Kropkowane podkreślenie zakresu (niepewne słowa — inaczej niż ostrzeżenia)."""
    selection = QTextEdit.ExtraSelection()
    selection.cursor = cursor
    selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
    selection.format.setUnderlineColor(color)
    return selection
