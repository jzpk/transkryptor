"""Panel ostrzeżeń walidatora notacji.

Lista prezentuje wyniki ``notation.validate`` (kod, komunikat, pozycja) -
UI nie interpretuje reguł, jedynie wyświetla je i nawiguje do zakresu
w tekście po wybraniu pozycji. Menu kontekstowe pozycji ma „Ignoruj tutaj”.

``WarningsCard`` to karta pod edytorem z nagłówkiem (licznik, wskazówka,
„Ujednolić wielokropki”) i listą, którą można zwinąć do samego nagłówka -
edytor dostaje wtedy całą wysokość (zgł. #58).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSplitter,
    QToolButton,
    QVBoxLayout,
)

from transkryptor.i18n import tr
from transkryptor.notation.validator import SEVERITY_HINT, NotationWarning
from transkryptor.ui import icons
from transkryptor.ui.layout import header_row, label, shrinkable
from transkryptor.ui.theme import set_props, tokens

# Najmniejsza wysokość rozwiniętej karty i wysokość po rozwinięciu karty
# zwiniętej od startu (z nagłówkiem).
MIN_EXPANDED_HEIGHT = 96
EXPANDED_HEIGHT = 140
# Brak ograniczenia wysokości widżetu (QWIDGETSIZE_MAX).
_NO_MAXIMUM = 16777215


class WarningsPanel(QListWidget):
    """Lista ostrzeżeń z sygnałem nawigacji do zakresu w tekście."""

    warning_activated = Signal(int, int)
    ignore_requested = Signal(object)  # NotationWarning

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._warnings: list[NotationWarning] = []
        self.setObjectName("warnings_panel")
        set_props(self, flat=True)
        self.setIconSize(icons.ICON_SIZE)
        self.itemActivated.connect(self._on_item_activated)
        self.itemClicked.connect(self._on_item_activated)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def set_warnings(self, warnings: list[NotationWarning]) -> None:
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

    def warning_at_row(self, row: int) -> NotationWarning | None:
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


class WarningsCard(QFrame):
    """Karta ostrzeżeń: nagłówek z przełącznikiem zwijania i lista."""

    expanded_changed = Signal(bool)

    def __init__(
        self, panel: WarningsPanel, count_label: QLabel, unify_action: QAction
    ) -> None:
        super().__init__()
        self.setObjectName("warnings_card")
        set_props(self, card=True)
        self.panel = panel
        self.toggle = QToolButton()
        self.toggle.setObjectName("warnings_toggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setText(tr("main.warnings"))
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.setToolTip(tr("main.warnings.toggle.tooltip"))
        self._hint = shrinkable(label(tr("main.warnings.hint"), "muted"))
        unify_button = QToolButton()
        unify_button.setDefaultAction(unify_action)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(
            header_row(
                (12, 8, 16, 8),
                self.toggle,
                count_label,
                None,
                self._hint,
                unify_button,
            )
        )
        layout.addWidget(panel, stretch=1)
        self.setMinimumHeight(MIN_EXPANDED_HEIGHT)
        # Wysokość sprzed zwinięcia - przywracana po rozwinięciu.
        self._expanded_height = EXPANDED_HEIGHT
        self.toggle.toggled.connect(self._on_toggled)

    @property
    def expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self.toggle.isChecked():
            self.toggle.setChecked(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.panel.setVisible(expanded)
        self._hint.setVisible(expanded)
        if expanded:
            self.setMinimumHeight(MIN_EXPANDED_HEIGHT)
            self.setMaximumHeight(_NO_MAXIMUM)
            self._resize_in_splitter(self._expanded_height)
        else:
            if self.isVisible():
                self._expanded_height = max(MIN_EXPANDED_HEIGHT, self.height())
            # Zwinięta karta to sam nagłówek; reszta wysokości trafia do edytora.
            height = self.sizeHint().height()
            self.setMinimumHeight(0)
            self.setMaximumHeight(height)
            self._resize_in_splitter(height)
        self.expanded_changed.emit(expanded)

    def _resize_in_splitter(self, height: int) -> None:
        """Nowa wysokość karty w podziale okna - kosztem albo na rzecz sąsiada.

        ``QSplitter`` sam nie oddaje miejsca zwolnionego przez zwiniętą kartę.
        """
        splitter = self.parentWidget()
        if not isinstance(splitter, QSplitter) or splitter.count() < 2:
            return
        sizes = splitter.sizes()
        index = splitter.indexOf(self)
        neighbour = 0 if index != 0 else 1
        if not sizes[index] and not sizes[neighbour]:
            return  # podział jeszcze nie ułożony (okno niewidoczne)
        delta = height - sizes[index]
        if delta > 0:
            delta = min(delta, max(0, sizes[neighbour] - MIN_EXPANDED_HEIGHT))
        sizes[index] += delta
        sizes[neighbour] -= delta
        splitter.setSizes(sizes)
