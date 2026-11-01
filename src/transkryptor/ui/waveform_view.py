"""Widok fali dźwiękowej z nakładkami (``ui/waveform.py`` składa panel).

``WaveformView`` rysuje falę w ``paintEvent`` w kolorach motywu: kursor
pozycji, pętlę A-B, segmenty ASR (paski w kolorze pewności), ręczne
znaczniki czasu, tło sprawdzonych fragmentów (postęp weryfikacji) oraz mapę
pokrycia transkrypcji - pasek fragmentów z tekstem nad segmentami i tło
luk bez tekstu. Klik przewija nagranie, przeciągnięcie ustawia pętlę A-B
(``ui/time_selection.py``), ``Ctrl`` + kółko powiększa, kółko przewija
w poziomie.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from transkryptor.audio.envelope import Envelope
from transkryptor.i18n import tr
from transkryptor.ui.asr_transcription_section import LOW_CONFIDENCE
from transkryptor.ui.theme import Tokens, tokens
from transkryptor.ui.time_selection import LOOP, SEEK, DragSelection

WAVEFORM_HEIGHT = 72
# Największe powiększenie: tyle ms na piksel.
MIN_MS_PER_PX = 2.0
ZOOM_STEP = 1.5
SEGMENT_STRIP_PX = 4
# Pasek pokrycia transkrypcji tuż nad paskiem segmentów ASR.
COVERAGE_STRIP_PX = 3
# Pasek sprawdzonych fragmentów u góry fali (widoczny także przy gęstej fali).
VERIFIED_STRIP_PX = 3
# Przezroczystość tła luk w transkrypcji.
GAP_ALPHA = 110

# Segment ASR na fali: (początek ms, koniec ms, pewność 0-1).
SegmentSpan = tuple[int, int, float]
Range = tuple[int, int]


class WaveformView(QWidget):
    """Fala dźwiękowa nagrania z kursorem, pętlą, segmentami i znacznikami."""

    seek_requested = Signal(int)  # ms
    loop_requested = Signal(int, int)  # początek, koniec ms
    view_changed = Signal()  # powiększenie albo przewinięcie

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("waveform")
        self.setMinimumHeight(WAVEFORM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setToolTip(tr("waveform.tooltip"))
        self._envelope: Envelope | None = None
        self._peaks: Sequence[int] = b""
        self._scale = 1.0
        self.duration_ms = 0
        self.position_ms = 0
        self.loop: Range | None = None
        self.segments: list[SegmentSpan] = []
        self.markers: list[int] = []
        # Sprawdzone zakresy nagrania (ms) - tło pod falą.
        self.verified: list[Range] = []
        # Mapa pokrycia: fragmenty z tekstem i luki bez tekstu (ms).
        self.covered: list[Range] = []
        self.gaps: list[Range] = []
        self.view_start_ms = 0.0
        self.ms_per_px = 0.0  # 0 = całe nagranie w szerokości widoku
        self._drag = DragSelection(self.ms_at)

    # --- dane ---------------------------------------------------------------

    @property
    def envelope(self) -> Envelope | None:
        return self._envelope

    def set_envelope(self, envelope: Envelope | None) -> None:
        self._envelope = envelope
        self._peaks = envelope.peaks if envelope is not None else b""
        top = max(self._peaks, default=0)
        # Ciche nagrania terenowe: fala skalowana do najgłośniejszego miejsca.
        self._scale = 1.0 / top if top else 1.0
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        self.duration_ms = max(0, duration_ms)
        self._clamp_view()
        self.update()

    def set_position(self, position_ms: int) -> None:
        self.position_ms = position_ms
        # Kursor poza powiększonym widokiem: widok przechodzi za nim.
        if self.ms_per_px and not self._drag.dragging:
            start, end = self.visible_range_ms()
            if not start <= position_ms <= end:
                self.view_start_ms = position_ms - (end - start) * 0.1
                self._clamp_view()
                self.view_changed.emit()
        self.update()

    def set_coverage(self, covered: Sequence[Range], gaps: Sequence[Range]) -> None:
        self.covered = list(covered)
        self.gaps = list(gaps)
        self.update()

    # --- geometria ------------------------------------------------------------

    def effective_ms_per_px(self) -> float:
        width = max(1, self.width())
        fit = self.duration_ms / width if self.duration_ms else 1.0
        return min(self.ms_per_px, fit) if self.ms_per_px else fit

    def visible_range_ms(self) -> tuple[float, float]:
        scale = self.effective_ms_per_px()
        return self.view_start_ms, self.view_start_ms + scale * self.width()

    def ms_at(self, x: float) -> int:
        position = self.view_start_ms + x * self.effective_ms_per_px()
        return int(max(0, min(self.duration_ms, position)))

    def x_at(self, ms: float) -> float:
        return (ms - self.view_start_ms) / self.effective_ms_per_px()

    def zoom(self, factor: float, anchor_x: float | None = None) -> None:
        """Powiększa (``factor`` < 1) albo pomniejsza widok wokół punktu."""
        if not self.duration_ms:
            return
        anchor_x = self.width() / 2 if anchor_x is None else anchor_x
        anchor_ms = self.view_start_ms + anchor_x * self.effective_ms_per_px()
        fit = self.duration_ms / max(1, self.width())
        scale = self.effective_ms_per_px() * factor
        self.ms_per_px = 0.0 if scale >= fit else max(MIN_MS_PER_PX, scale)
        self.view_start_ms = anchor_ms - anchor_x * self.effective_ms_per_px()
        self._clamp_view()
        self.view_changed.emit()
        self.update()

    def scroll_to(self, start_ms: float) -> None:
        self.view_start_ms = start_ms
        self._clamp_view()
        self.update()

    def show_range(self, start_ms: int, end_ms: int) -> None:
        """Przewija powiększony widok tak, by pokazać ``[start_ms, end_ms)``."""
        view_start, view_end = self.visible_range_ms()
        if not self.ms_per_px or (start_ms >= view_start and end_ms <= view_end):
            return
        self.scroll_to(start_ms - (view_end - view_start) * 0.1)
        self.view_changed.emit()

    def _clamp_view(self) -> None:
        span = self.effective_ms_per_px() * self.width()
        limit = max(0.0, self.duration_ms - span)
        self.view_start_ms = max(0.0, min(self.view_start_ms, limit))

    # --- rysowanie ----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(t.surface_alt))
        if self.duration_ms:
            wave_height = self.height() - SEGMENT_STRIP_PX - COVERAGE_STRIP_PX - 2
            self._paint_backgrounds(painter, t, wave_height)
            self._paint_wave(painter, t, wave_height / 2)
            self._paint_strips(painter, t)
            self._paint_markers(painter, t)
        painter.end()

    def _spans(self, ranges: Sequence[Range]) -> list[tuple[float, float]]:
        """Zakresy (ms) jako widoczne odcinki ``(lewo, szerokość)`` w pikselach."""
        width = self.width()
        spans = []
        for start, end in ranges:
            left, right = self.x_at(start), self.x_at(end)
            if right >= 0 and left <= width:
                spans.append((left, max(1.0, right - left)))
        return spans

    def _paint_backgrounds(self, painter: QPainter, t: Tokens, height: float) -> None:
        gap = QColor(t.danger_soft)
        gap.setAlpha(GAP_ALPHA)
        for left, span in self._spans(self.gaps):
            painter.fillRect(QRectF(left, 0, span, height), gap)
        verified = QColor(t.success_soft)
        for left, span in self._spans(self.verified):
            painter.fillRect(QRectF(left, 0, span, height), verified)
        loop = self._drag.selection() or self.loop
        if loop is not None:
            soft = QColor(t.accent)
            soft.setAlpha(50)
            left, right = self.x_at(loop[0]), self.x_at(loop[1])
            painter.fillRect(QRectF(left, 0, right - left, height), soft)

    def _paint_wave(self, painter: QPainter, t: Tokens, middle: float) -> None:
        width = self.width()
        if not self._peaks:
            painter.setPen(QColor(t.border))
            painter.drawLine(QPointF(0, middle), QPointF(width, middle))
            return
        painter.setPen(QColor(t.accent))
        step = self._envelope.step_ms if self._envelope is not None else 10
        scale = self.effective_ms_per_px()
        count = len(self._peaks)
        for x in range(width):
            first = int((self.view_start_ms + x * scale) / step)
            last = max(first + 1, int((self.view_start_ms + (x + 1) * scale) / step))
            if first >= count:
                break
            peak = max(self._peaks[first : min(last, count)]) * self._scale
            half = max(0.5, peak * (middle - 1))
            painter.drawLine(QPointF(x, middle - half), QPointF(x, middle + half))

    def _paint_strips(self, painter: QPainter, t: Tokens) -> None:
        height = self.height()
        segment_top = height - SEGMENT_STRIP_PX
        for start, end, confidence in self.segments:
            for left, span in self._spans([(start, end)]):
                color = QColor(t.success if confidence >= LOW_CONFIDENCE else t.warning)
                painter.fillRect(
                    QRectF(left, segment_top, max(1.0, span - 1), SEGMENT_STRIP_PX),
                    color,
                )
        coverage_top = segment_top - COVERAGE_STRIP_PX - 1
        for left, span in self._spans(self.covered):
            painter.fillRect(
                QRectF(left, coverage_top, span, COVERAGE_STRIP_PX), QColor(t.accent)
            )
        for left, span in self._spans(self.gaps):
            painter.fillRect(
                QRectF(left, coverage_top, span, COVERAGE_STRIP_PX), QColor(t.danger)
            )
        for left, span in self._spans(self.verified):
            painter.fillRect(
                QRectF(left, 0, span, VERIFIED_STRIP_PX), QColor(t.success)
            )

    def _paint_markers(self, painter: QPainter, t: Tokens) -> None:
        width = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.text))
        for marker in self.markers:
            marker_x = self.x_at(marker)
            if 0 <= marker_x <= width:
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(marker_x - 4, 0),
                            QPointF(marker_x + 4, 0),
                            QPointF(marker_x, 6),
                        ]
                    )
                )
        painter.setPen(QColor(t.danger))
        cursor_x = self.x_at(self.position_ms)
        painter.drawLine(QPointF(cursor_x, 0), QPointF(cursor_x, self.height()))

    # --- mysz -----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.duration_ms:
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

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta or not self.duration_ms:
            event.ignore()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1 / ZOOM_STEP if delta > 0 else ZOOM_STEP
            self.zoom(factor, event.position().x())
        elif self.ms_per_px:
            span = self.visible_range_ms()[1] - self.view_start_ms
            self.scroll_to(self.view_start_ms - span * 0.1 * (delta / 120))
            self.view_changed.emit()
        else:
            event.ignore()
            return
        event.accept()

    def resizeEvent(self, event) -> None:  # API Qt
        super().resizeEvent(event)
        self._clamp_view()
        self.view_changed.emit()
