"""Menu przycisku „Podświetlenia” na pasku narzędzi.

Menu składa się z sekcji (kontrolerów podświetleń), oddzielonych kreską.
Każda sekcja dopisuje swoje pozycje przy każdym rozwinięciu menu, więc
liczniki i stan zawsze odpowiadają bieżącemu tekstowi.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from PySide6.QtWidgets import QMenu


class MenuSection(Protocol):
    def fill_menu(self, menu: QMenu) -> None: ...


class HighlightsMenu:
    """Wypełnia menu podświetleń pozycjami kolejnych sekcji."""

    def __init__(self, menu: QMenu, sections: Sequence[MenuSection]) -> None:
        self.menu = menu
        self._sections = tuple(sections)
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(self.refresh)

    def refresh(self) -> None:
        self.menu.clear()
        for index, section in enumerate(self._sections):
            if index:
                self.menu.addSeparator()
            section.fill_menu(self.menu)
