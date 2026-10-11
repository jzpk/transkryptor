"""Panel ostrzeżeń walidatora notacji.

Lista prezentuje wyniki ``notation.validate`` (kod, komunikat, pozycja) —
UI nie interpretuje reguł, jedynie wyświetla je i nawiguje do zakresu
w tekście po wybraniu pozycji. Menu kontekstowe pozycji ma „Ignoruj tutaj”.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu

from transkryptor.i18n import tr
from transkryptor.notation.validator import SEVERITY_HINT, Warning
from transkryptor.ui import icons
from transkryptor.ui.theme import set_props, tokens


class WarningsPanel(QListWidget):
    """Lista ostrzeżeń z sygnałem nawigacji do zakresu w tekście."""

    warning_activated = Signal(int, int)
    ignore_requested = Signal(object)  # Warning

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._warnings: list[Warning] = []
        self.setObjectName("warnings_panel")
        set_props(self, flat=True)
        self.setIconSize(icons.ICON_SIZE)
        self.itemActivated.connect(self._on_item_activated)
        self.itemClicked.connect(self._on_item_activated)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_warnings(self, warnings: list[Warning]) -> None:
        """Zastępuje listę ostrzeżeń wynikiem walidacji."""
        self._warnings = list(warnings)
        self.clear()
        if not self._warnings:
            t = tokens()
            item = QListWidgetItem(
                icons.icon("check_circle", t.success), tr("warnings.empty")
            )
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(item)
            return
        t = tokens()
        alert = icons.icon("alert", t.warning)
        hint = icons.icon("alert", t.text_muted)
        for warning in self._warnings:
            is_hint = warning.severity == SEVERITY_HINT
            item = QListWidgetItem(
                hint if is_hint else alert,
                tr(
                    "warnings.item",
                    code=warning.code,
                    message=warning.message,
                    position=warning.start,
                ),
            )
            if is_hint:
                # Wskazówka (np. VAL-05) ma niższą rangę niż błąd struktury.
                item.setForeground(QColor(t.text_muted))
            item.setToolTip(tr("warnings.item.tooltip"))
            self.addItem(item)

    def warning_count(self) -> int:
        """Liczba aktywnych ostrzeżeń (0, gdy lista pokazuje stan pusty)."""
        return len(self._warnings)

    def has_errors(self) -> bool:
        """Czy lista zawiera ostrzeżenia wyższej rangi niż wskazówki."""
        return any(w.severity != SEVERITY_HINT for w in self._warnings)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        index = self.row(item)
        if 0 <= index < len(self._warnings):
            warning = self._warnings[index]
            self.warning_activated.emit(warning.start, warning.end)

    def warning_at_row(self, row: int) -> Warning | None:
        return self._warnings[row] if 0 <= row < len(self._warnings) else None

    def _on_context_menu(self, point: QPoint) -> None:
        item = self.itemAt(point)
        warning = self.warning_at_row(self.row(item)) if item is not None else None
        if warning is None:
            return
        menu = QMenu(self)
        action = menu.addAction(tr("warnings.ignore_here", code=warning.code))
        action.triggered.connect(
            lambda _checked=False: self.ignore_requested.emit(warning)
        )
        menu.exec(self.viewport().mapToGlobal(point))
