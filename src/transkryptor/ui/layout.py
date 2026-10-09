"""Pomocnicze funkcje składania kart i nagłówków okna głównego."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from transkryptor.ui.theme import set_props


def card(
    header: QHBoxLayout,
    *widgets: QWidget,
    stretch_first: bool = False,
    stretch_index: int | None = None,
) -> QFrame:
    """Karta z nagłówkiem i widżetami pod nim (jeden może się rozciągać)."""
    if stretch_first:
        stretch_index = 0
    frame = QFrame()
    set_props(frame, card=True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addLayout(header)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, stretch=1 if index == stretch_index else 0)
    return frame


def header_row(
    margins: tuple[int, int, int, int], *items: QWidget | int | None
) -> QHBoxLayout:
    """Wiersz nagłówka karty: widżety, ``None`` = rozciągnięcie, liczba = odstęp."""
    row = QHBoxLayout()
    row.setContentsMargins(*margins)
    row.setSpacing(8)
    for item in items:
        if item is None:
            row.addStretch(1)
        elif isinstance(item, int):
            row.addSpacing(item)
        else:
            row.addWidget(item)
    return row


def label(text: str, role: str) -> QLabel:
    widget = QLabel(text)
    set_props(widget, role=role)
    return widget


def buddy_caption(text: str, buddy: QWidget) -> QLabel:
    caption = label(text, "caption")
    caption.setBuddy(buddy)
    return caption


def author_field() -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText("Imię i nazwisko transkrybenta")
    field.setClearButtonEnabled(True)
    field.setMinimumWidth(220)
    return field


def date_field() -> QDateEdit:
    field = QDateEdit(QDate.currentDate())
    field.setCalendarPopup(True)
    field.setDisplayFormat("dd.MM.yyyy")
    field.setSpecialValueText(" ")
    return field


def side_dock(
    window: QMainWindow, title: str, name: str, widget: QWidget
) -> QDockWidget:
    """Dok po prawej stronie okna (przenośny, odczepialny, zamykany)."""
    dock = QDockWidget(title, window)
    dock.setObjectName(name)
    dock.setWidget(widget)
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable
    )
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    window.resizeDocks([dock], [420], Qt.Orientation.Horizontal)
    return dock


def words_label(count: int) -> str:
    """Odmiana „słowo” po liczebniku (1 słowo, 2 słowa, 5 słów)."""
    if count == 1:
        return "słowo"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "słowa"
    return "słów"
