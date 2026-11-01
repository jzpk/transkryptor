"""Miniatura całego nagrania z mapą pokrycia transkrypcji.

Wąski pasek pod falą pokazuje całe nagranie niezależnie od powiększenia:
fragmenty z tekstem (akcent), luki bez tekstu (kolor błędu), ramkę
widocznego zakresu powiększonej fali i kursor odtwarzania. Klik przewija
nagranie - szybki skok do luki zauważonej na miniaturze.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from transkryptor.i18n import tr
from transkryptor.ui.theme import tokens

OVERVIEW_HEIGHT = 10

Range = tuple[int, int]


class CoverageOverview(QWidget):
    """Pokrycie całego nagrania w jednym pasku."""

    seek_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("coverage_overview")
        self.setFixedHeight(OVERVIEW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("coverage.overview.tooltip"))
        self.duration_ms = 0
        self.position_ms = 0
        self.covered: list[Range] = []
        self.gaps: list[Range] = []
        self.visible: Range | None = None

    def set_coverage(self, covered: Sequence[Range], gaps: Sequence[Range]) -> None:
        self.covered = list(covered)
        self.gaps = list(gaps)
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        self.duration_ms = max(0, duration_ms)
        self.update()

    def set_position(self, position_ms: int) -> None:
        self.position_ms = position_ms
        self.update()

    def set_window(self, window: Range | None) -> None:
        """Widoczny zakres fali (None - fala pokazuje całe nagranie)."""
        self.visible = window
        self.update()

    def x_at(self, ms: float) -> float:
        return ms / self.duration_ms * self.width() if self.duration_ms else 0.0

    def ms_at(self, x: float) -> int:
        fraction = max(0.0, min(1.0, x / max(1, self.width())))
        return int(fraction * self.duration_ms)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens()
        painter = QPainter(self)
        height = self.height()
        painter.fillRect(self.rect(), QColor(t.surface_alt))
        if self.duration_ms:
            for ranges, color in ((self.covered, t.accent), (self.gaps, t.danger)):
                for start, end in ranges:
                    left = self.x_at(start)
                    width = max(1.0, self.x_at(end) - left)
                    painter.fillRect(QRectF(left, 2, width, height - 4), QColor(color))
            if self.visible is not None:
                pen = QPen(QColor(t.text))
                painter.setPen(pen)
                left = self.x_at(self.visible[0])
                width = max(2.0, self.x_at(self.visible[1]) - left)
                painter.drawRect(QRectF(left, 0.5, width, height - 1))
            painter.setPen(QColor(t.danger))
            x = self.x_at(self.position_ms)
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.duration_ms:
            self.seek_requested.emit(self.ms_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)
