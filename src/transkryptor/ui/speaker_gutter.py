"""Kolumna etykiet mówców po lewej stronie edytora.

Mówca akapitu jest właściwością bloku ``QTextDocument`` (``SPEAKER_PROPERTY``),
nie tekstem - etykieta ``B:`` jest rysowana obok akapitu i nie da się jej
edytować ani przypadkiem skasować. Kolumna jest widżetem w marginesie widoku
edytora (``setViewportMargins``), wzorem numerów wierszy w edytorach kodu.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QTextBlock,
    QTextFormat,
)
from PySide6.QtWidgets import QTextEdit, QWidget

from transkryptor.ui.theme import tokens

SPEAKER_PROPERTY = QTextFormat.Property.UserProperty + 1
GUTTER_PADDING = 8


def block_speaker(block: QTextBlock) -> str | None:
    """Klucz mówcy akapitu albo None."""
    value = block.blockFormat().property(SPEAKER_PROPERTY)
    return value if isinstance(value, str) and value else None


def label_text(key: str) -> str:
    return f"{key}:"


class SpeakerGutter(QWidget):
    """Rysuje etykiety mówców widocznych akapitów; klik otwiera menu mówców."""

    def __init__(
        self, editor: QTextEdit, on_click: Callable[[QTextBlock, QPoint], None]
    ) -> None:
        super().__init__(editor)
        self._editor = editor
        self._on_click = on_click
        self._width = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def label_font(self) -> QFont:
        font = QFont(self._editor.font())
        font.setBold(True)
        return font

    def set_keys(self, keys: list[str]) -> None:
        """Dopasowuje szerokość do najdłuższej etykiety; brak kluczy chowa kolumnę."""
        width = 0
        if keys:
            metrics = QFontMetrics(self.label_font())
            width = (
                max(metrics.horizontalAdvance(label_text(key)) for key in keys)
                + 2 * GUTTER_PADDING
            )
        if width == self._width:
            return
        self._width = width
        self._editor.setViewportMargins(self._width, 0, 0, 0)
        self.setVisible(self._width > 0)
        self.update_geometry()

    @property
    def gutter_width(self) -> int:
        return self._width

    def update_geometry(self) -> None:
        rect = self._editor.contentsRect()
        self.setGeometry(QRect(rect.left(), rect.top(), self._width, rect.height()))

    def _visible_blocks(self) -> list[tuple[QTextBlock, int]]:
        """Bloki widoczne w oknie z górną krawędzią w układzie kolumny."""
        editor = self._editor
        document = editor.document()
        layout = document.documentLayout()
        offset = editor.verticalScrollBar().value()
        height = editor.viewport().height()
        block = editor.cursorForPosition(QPoint(0, 0)).block()
        result: list[tuple[QTextBlock, int]] = []
        while block.isValid():
            top = int(layout.blockBoundingRect(block).top()) - offset
            if top > height:
                break
            result.append((block, top))
            block = block.next()
        return result

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._width:
            return
        painter = QPainter(self)
        painter.setFont(self.label_font())
        painter.setPen(QColor(tokens().accent))
        metrics = QFontMetrics(self.label_font())
        for block, top in self._visible_blocks():
            key = block_speaker(block)
            if key is None:
                continue
            first_line = block.layout().lineAt(0) if block.layout() else None
            line_height = (
                int(first_line.height()) if first_line is not None else metrics.height()
            )
            rect = QRect(0, top, self._width - GUTTER_PADDING, max(line_height, 1))
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label_text(key),
            )
        painter.end()

    def block_at(self, y: int) -> QTextBlock | None:
        """Akapit na wysokości ``y`` (nad pierwszym - pierwszy widoczny)."""
        blocks = self._visible_blocks()
        candidate: QTextBlock | None = blocks[0][0] if blocks else None
        for block, top in blocks:
            if top > y:
                break
            candidate = block
        return candidate

    def mousePressEvent(self, event: QMouseEvent) -> None:
        block = self.block_at(int(event.position().y()))
        if block is not None:
            self._on_click(block, event.globalPosition().toPoint())
