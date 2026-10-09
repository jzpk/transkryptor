"""Konwersja pozycji tekstu między Pythonem a Qt.

``QTextDocument`` liczy pozycje w jednostkach UTF-16, a Python (``Document``,
``notation``, wyszukiwanie) — w punktach kodowych. Znak spoza BMP (emoji,
znaki matematyczne) zajmuje w Qt dwie jednostki, więc każda pozycja za nim
różni się o 1. Wszystkie miejsca styku z Qt przeliczają pozycje przez
:class:`PositionMap`.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right

_BMP_MAX = "￿"


def utf16_len(text: str) -> int:
    """Długość tekstu w jednostkach UTF-16 (pozycjach Qt)."""
    return len(text) + sum(1 for char in text if char > _BMP_MAX)


class PositionMap:
    """Przelicza pozycje jednego tekstu: punkty kodowe ↔ jednostki UTF-16.

    Tekst bez znaków spoza BMP (typowy przypadek) daje odwzorowanie
    tożsamościowe bez dodatkowego kosztu.
    """

    def __init__(self, text: str) -> None:
        # Indeksy (w Pythonie) znaków spoza BMP, rosnąco.
        self._astral = [i for i, char in enumerate(text) if char > _BMP_MAX]
        # Pozycja Qt tuż za każdym takim znakiem.
        self._astral_qt_ends = [i + k + 2 for k, i in enumerate(self._astral)]

    def to_qt(self, index: int) -> int:
        """Pozycja Pythona → pozycja Qt."""
        if not self._astral:
            return index
        return index + bisect_left(self._astral, index)

    def to_py(self, position: int) -> int:
        """Pozycja Qt → pozycja Pythona.

        Pozycja w środku pary surogatów wskazuje początek znaku.
        """
        if not self._astral:
            return position
        before = bisect_right(self._astral_qt_ends, position)
        index = position - before
        if before < len(self._astral) and self.to_qt(self._astral[before]) < position:
            index -= 1
        return index
