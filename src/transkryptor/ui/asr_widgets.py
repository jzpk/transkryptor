"""Wspólne elementy panelu szkicu ASR: kroki z numerem, nagłówki, separator."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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
