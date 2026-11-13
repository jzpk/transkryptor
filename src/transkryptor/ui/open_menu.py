"""Menu przycisku „Otwórz” na pasku narzędzi.

Ostatnie projekty, import DOCX, polecenia dokładane przez kontrolery
(``add_actions``, np. otwarcie paczki), porównanie wersji i czyszczenie
listy ostatnich. Menu odświeża się przy każdym rozwinięciu.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from transkryptor.i18n import tr
from transkryptor.ui import icons


@dataclass(frozen=True)
class OpenMenuHandlers:
    recent_projects: Callable[[], list[str]]
    open_recent: Callable[[str], object]
    import_docx: Callable[[], None]
    compare: Callable[[], object]
    clear_recent: Callable[[], None]


class OpenMenu:
    """Menu „Otwórz” z listą ostatnich projektów i jego akcje."""

    def __init__(self, window: QMainWindow, handlers: OpenMenuHandlers) -> None:
        self._handlers = handlers
        # Dodatkowe polecenia menu (``add_actions``).
        self._extras: list[QAction] = []
        self.import_docx_action = QAction(tr("toolbar.import_docx"), window)
        self.import_docx_action.setToolTip(tr("toolbar.import_docx.tooltip"))
        self.import_docx_action.triggered.connect(
            lambda _checked=False: handlers.import_docx()
        )
        self.compare_action = QAction(tr("toolbar.compare"), window)
        icons.set_icon(self.compare_action, "compare", "text", "text_muted")
        self.compare_action.setToolTip(tr("toolbar.compare.tooltip"))
        self.compare_action.triggered.connect(lambda _checked=False: handlers.compare())
        self.clear_recent_action = QAction(tr("toolbar.clear_recent"), window)
        self.clear_recent_action.triggered.connect(
            lambda _checked=False: handlers.clear_recent()
        )
        # Tytuł menu widać, gdy jest podmenu „Więcej poleceń”.
        self.menu = QMenu(tr("toolbar.recent"), window)
        self.menu.aboutToShow.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Ostatnie projekty, import DOCX, porównanie, czyszczenie."""
        menu = self.menu
        menu.clear()
        recent = self._handlers.recent_projects()
        for path in recent:
            action = menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.setStatusTip(path)
            action.triggered.connect(
                lambda _checked=False, chosen=path: self._handlers.open_recent(chosen)
            )
        if not recent:
            placeholder = menu.addAction(tr("toolbar.recent.empty"))
            placeholder.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.import_docx_action)
        menu.addActions(self._extras)
        menu.addAction(self.compare_action)
        menu.addAction(self.clear_recent_action)
        self.clear_recent_action.setEnabled(bool(recent))

    def add_actions(self, actions: Sequence[QAction]) -> None:
        """Polecenia za importem DOCX."""
        self._extras.extend(actions)
        self.refresh()
