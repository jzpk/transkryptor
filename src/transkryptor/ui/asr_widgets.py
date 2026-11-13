"""Wspólne elementy panelu szkicu ASR: kroki, nagłówki, separator, zwijanie."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.ui.theme import set_props


class AutoHideLabel(QLabel):
    """Etykieta ukryta, gdy nie ma treści - pusta nie zostawia dziury."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:  # API Qt
        super().setText(text)
        self.setVisible(bool(text))


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    set_props(label, role="section")
    return label


def divider() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    set_props(line, role="divider")
    return line


def step(number: str, title: str, items: list) -> QWidget:
    """Krok panelu: numer w kółku, tytuł i treść wcięta pod tytułem."""
    badge = QLabel(number)
    set_props(badge, role="step")
    header = QHBoxLayout()
    header.setSpacing(10)
    header.addWidget(badge)
    header.addWidget(section_label(title), stretch=1)
    body = QVBoxLayout()
    body.setContentsMargins(32, 0, 0, 0)
    body.setSpacing(8)
    for item in items:
        if isinstance(item, QWidget):
            body.addWidget(item)
        else:
            body.addLayout(item)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addLayout(header)
    layout.addLayout(body)
    return widget


class Collapsible(QWidget):
    """Sekcja zwijana przełącznikiem ze strzałką; domyślnie zwinięta.

    Przełącznik ma nazwę ``<name>_toggle`` (cel samouczka, gdy treść
    jest schowana).
    """

    expanded_changed = Signal(bool)

    def __init__(self, name: str, title: str, items: list) -> None:
        super().__init__()
        self.setObjectName(name)
        self._title = title
        self._model: QAbstractItemModel | None = None
        self.toggle = QToolButton()
        self.toggle.setObjectName(f"{name}_toggle")
        self.toggle.setCheckable(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setText(title)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        for item in items:
            if isinstance(item, QLayout):
                body.addLayout(item)
            else:
                body.addWidget(item)
        self.body.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.body, stretch=1)
        self.toggle.toggled.connect(self._on_toggled)

    @property
    def expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)

    def set_count(self, count: int) -> None:
        """Liczba pozycji w tytule - widać ją także po zwinięciu."""
        self.toggle.setText(f"{self._title} ({count})" if count else self._title)

    def count_rows(self, model: QAbstractItemModel) -> None:
        """Liczba w tytule podąża za liczbą wierszy modelu listy."""
        self._model = model
        model.rowsInserted.connect(self._on_rows_changed)
        model.rowsRemoved.connect(self._on_rows_changed)
        model.modelReset.connect(self._on_rows_changed)

    def _on_rows_changed(self) -> None:
        if self._model is not None:
            self.set_count(self._model.rowCount())

    def _on_toggled(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.body.setVisible(expanded)
        self.expanded_changed.emit(expanded)
