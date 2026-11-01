"""Widok spektrogramu i jego zwijany panel pod falą dźwiękową.

``SpectrogramView`` rysuje ``audio.spectrogram.Spectrogram`` jako obraz
z paletą motywu (tło karty → akcent → kolor tekstu, więc w motywie jasnym
energia jest ciemna, a w ciemnym - jasna) i oś czasu fragmentu: kursor
odtwarzania, pętlę A-B, klik przewija nagranie, przeciągnięcie ustawia
pętlę - tak jak na fali (``ui/time_selection.py``). ``SpectrogramPanel``
to nagłówek z przełącznikiem i stanem (np. „zaznacz krótszy fragment”)
oraz widok.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.audio.spectrogram import Spectrogram
from transkryptor.i18n import tr
from transkryptor.ui.theme import Tokens, set_props, tokens
from transkryptor.ui.time_selection import LOOP, SEEK, DragSelection

SPECTROGRAM_HEIGHT = 140


def palette(t: Tokens) -> list[int]:
    """256 kolorów ARGB: tło karty → akcent → tekst (zgodnie z motywem)."""
    stops = [QColor(t.surface_alt), QColor(t.accent), QColor(t.text)]
    colors: list[int] = []
    for index in range(256):
        position = index / 255 * (len(stops) - 1)
        low = min(int(position), len(stops) - 2)
        fraction = position - low
        a, b = stops[low], stops[low + 1]
        mixed = QColor(
            round(a.red() + (b.red() - a.red()) * fraction),
            round(a.green() + (b.green() - a.green()) * fraction),
            round(a.blue() + (b.blue() - a.blue()) * fraction),
        )
        colors.append(mixed.rgb())
    return colors


class SpectrogramView(QWidget):
    """Obraz spektrogramu z kursorem i pętlą na osi czasu fragmentu."""

    seek_requested = Signal(int)
    loop_requested = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spectrogram")
        self.setMinimumHeight(SPECTROGRAM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setToolTip(tr("spectrogram.tooltip"))
        self.spectrogram: Spectrogram | None = None
        self.position_ms = 0
        self.loop: tuple[int, int] | None = None
        self._image: QImage | None = None
        self._theme: str | None = None
        self._drag = DragSelection(self.ms_at)

    def set_spectrogram(self, spectrogram: Spectrogram | None) -> None:
        self.spectrogram = spectrogram
        self._image = None
        self.update()

    def set_position(self, position_ms: int) -> None:
        if self.position_ms != position_ms:
            self.position_ms = position_ms
            if self.spectrogram is not None:
                self.update()

    def set_loop(self, loop: tuple[int, int] | None) -> None:
        self.loop = loop
        self.update()

    # --- oś czasu ---------------------------------------------------------

    def ms_at(self, x: float) -> int:
        spectrogram = self.spectrogram
        if spectrogram is None:
            return 0
        span = spectrogram.end_ms - spectrogram.start_ms
        fraction = max(0.0, min(1.0, x / max(1, self.width())))
        return int(spectrogram.start_ms + fraction * span)

    def x_at(self, ms: float) -> float:
        spectrogram = self.spectrogram
        if spectrogram is None:
            return 0.0
        span = max(1, spectrogram.end_ms - spectrogram.start_ms)
        return (ms - spectrogram.start_ms) / span * self.width()

    # --- rysowanie --------------------------------------------------------

    def image(self) -> QImage | None:
        """Obraz spektrogramu w paletach bieżącego motywu (z pamięcią)."""
        spectrogram = self.spectrogram
        if spectrogram is None or not spectrogram.columns or not spectrogram.rows:
            return None
        t = tokens()
        if self._image is None or self._theme != t.name:
            image = QImage(
                spectrogram.values,
                spectrogram.columns,
                spectrogram.rows,
                spectrogram.columns,
                QImage.Format.Format_Indexed8,
            )
            image.setColorTable(palette(t))
            # Kopia - obraz nie trzyma wskaźnika do bajtów spektrogramu.
            self._image = image.copy()
            self._theme = t.name
        return self._image

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(t.surface_alt))
        image = self.image()
        if image is not None and self.spectrogram is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(self.rect()), image)
            self._paint_overlays(painter, t, self.spectrogram)
        painter.end()

    def _paint_overlays(
        self, painter: QPainter, t: Tokens, spectrogram: Spectrogram
    ) -> None:
        height = self.height()
        loop = self._drag.selection() or self.loop
        if loop is not None:
            soft = QColor(t.accent)
            soft.setAlpha(60)
            left, right = self.x_at(loop[0]), self.x_at(loop[1])
            painter.fillRect(QRectF(left, 0, right - left, height), soft)
        painter.setPen(QColor(t.text_muted))
        khz = spectrogram.max_hz / 1000
        painter.drawText(QPointF(4, 12), tr("spectrogram.khz", khz=f"{khz:g}"))
        painter.drawText(QPointF(4, height - 4), "0")
        start, end = spectrogram.start_ms, spectrogram.end_ms
        if start <= self.position_ms <= end:
            painter.setPen(QColor(t.danger))
            x = self.x_at(self.position_ms)
            painter.drawLine(QPointF(x, 0), QPointF(x, height))

    # --- mysz -------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.spectrogram:
            self._drag.press(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag.move(event.position().x()):
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            result = self._drag.release()
            if result is not None:
                kind, start, end = result
                if kind == LOOP:
                    self.loop_requested.emit(start, end)
                elif kind == SEEK:
                    self.seek_requested.emit(start)
            self.update()
        super().mouseReleaseEvent(event)


class SpectrogramPanel(QWidget):
    """Zwijany spektrogram: przełącznik ze stanem i widok."""

    expanded_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spectrogram_panel")
        self.toggle = QToolButton()
        self.toggle.setObjectName("spectrogram_toggle")
        self.toggle.setCheckable(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setText(tr("spectrogram.title"))
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setToolTip(tr("spectrogram.toggle.tooltip"))
        self.status_label = QLabel()
        self.status_label.setObjectName("spectrogram_status")
        set_props(self.status_label, role="muted")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle)
        header.addWidget(self.status_label, stretch=1)
        self.view = SpectrogramView()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self.view)
        self.toggle.toggled.connect(self._on_toggled)
        self._apply_expanded(False)

    @property
    def expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self.toggle.isChecked():
            self.toggle.setChecked(expanded)
        else:
            self._apply_expanded(expanded)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _on_toggled(self, expanded: bool) -> None:
        self._apply_expanded(expanded)
        self.expanded_changed.emit(expanded)

    def _apply_expanded(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.view.setVisible(expanded)
        self.status_label.setVisible(expanded)
