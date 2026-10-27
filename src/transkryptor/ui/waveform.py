"""Fala dźwiękowa pod suwakiem odtwarzacza (faza 11, propozycja 6, ACC-50).

- ``EnvelopeThread`` liczy obwiednię w tle: suma SHA-256 nagrania → cache
  → dekodowanie PyAV (``audio/envelope.py``), z postępem i przerwaniem przy
  zmianie nagrania.
- ``WaveformView`` rysuje falę w ``paintEvent`` w kolorach motywu: kursor
  pozycji, pętlę A-B, segmenty ASR (paski w kolorze pewności), ręczne
  znaczniki czasu i tło sprawdzonych fragmentów (postęp weryfikacji). Klik przewija nagranie, przeciągnięcie ustawia pętlę A-B,
  ``Ctrl`` + kółko powiększa, kółko przewija w poziomie.
- ``WaveformPanel`` to zwijany nagłówek z postępem, widok i pasek przewijania.
- ``WaveformController`` łączy panel z odtwarzaczem, panelem ASR
  i kotwicami tekstu.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.asr.engine import SegmentResult
from transkryptor.audio.envelope import (
    Envelope,
    compute_envelope,
    load_cached,
    save_cached,
)
from transkryptor.audio.player import AudioPlayer
from transkryptor.document.project import file_sha256
from transkryptor.i18n import tr
from transkryptor.ui.asr_panel import LOW_CONFIDENCE
from transkryptor.ui.player_bar import PlayerBar
from transkryptor.ui.theme import set_props, tokens

logger = logging.getLogger(__name__)

WAVEFORM_HEIGHT = 72
# Przeciągnięcie krótsze niż tyle pikseli to klik (przewinięcie).
DRAG_THRESHOLD_PX = 4
# Największe powiększenie: tyle ms na piksel.
MIN_MS_PER_PX = 2.0
ZOOM_STEP = 1.5
SEGMENT_STRIP_PX = 4
# Pasek sprawdzonych fragmentów u góry fali (widoczny także przy gęstej fali).
VERIFIED_STRIP_PX = 3

# Segment ASR na fali: (początek ms, koniec ms, pewność 0-1).
SegmentSpan = tuple[int, int, float]


class EnvelopeThread(QThread):
    """Obwiednia nagrania w tle; ``envelope`` to wynik albo None."""

    progressed = Signal(float)

    def __init__(
        self,
        path: Path,
        cache_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.envelope: Envelope | None = None
        self.from_cache = False
        self._cache_dir = cache_dir
        self._percent = -1

    def run(self) -> None:
        cancel = self.isInterruptionRequested
        try:
            digest = file_sha256(self.path, should_cancel=cancel)
            cached = load_cached(digest, self._cache_dir)
            if cached is not None:
                self.envelope, self.from_cache = cached, True
                return
            envelope = compute_envelope(
                self.path, should_cancel=cancel, on_progress=self._report
            )
        except InterruptedError:
            return
        except Exception:  # fala jest pomocnicza; brak fali to nie błąd
            logger.warning("Waveform could not be computed", exc_info=True)
            return
        save_cached(digest, envelope, self._cache_dir)
        self.envelope = envelope

    def _report(self, fraction: float) -> None:
        """Postęp tylko przy zmianie pełnego procenta - nie zalewa wątku UI."""
        percent = int(fraction * 100)
        if percent != self._percent:
            self._percent = percent
            self.progressed.emit(fraction)


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
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setToolTip(tr("waveform.tooltip"))
        self._envelope: Envelope | None = None
        self._peaks: Sequence[int] = b""
        self._scale = 1.0
        self.duration_ms = 0
        self.position_ms = 0
        self.loop: tuple[int, int] | None = None
        self.segments: list[SegmentSpan] = []
        self.markers: list[int] = []
        # Sprawdzone zakresy nagrania (ms) - tło pod falą.
        self.verified: list[tuple[int, int]] = []
        self.view_start_ms = 0.0
        self.ms_per_px = 0.0  # 0 = całe nagranie w szerokości widoku
        self._press_x: float | None = None
        self._drag_x: float | None = None

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
        if self.ms_per_px and not self._dragging:
            start, end = self.visible_range_ms()
            if not start <= position_ms <= end:
                self.view_start_ms = position_ms - (end - start) * 0.1
                self._clamp_view()
                self.view_changed.emit()
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

    def _clamp_view(self) -> None:
        span = self.effective_ms_per_px() * self.width()
        limit = max(0.0, self.duration_ms - span)
        self.view_start_ms = max(0.0, min(self.view_start_ms, limit))

    @property
    def _dragging(self) -> bool:
        return self._drag_x is not None

    # --- rysowanie ----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens()
        painter = QPainter(self)
        width, height = self.width(), self.height()
        painter.fillRect(self.rect(), QColor(t.surface_alt))
        if not self.duration_ms:
            painter.end()
            return
        wave_height = height - SEGMENT_STRIP_PX - 2
        middle = wave_height / 2

        verified = QColor(t.success_soft)
        for start, end in self.verified:
            left, right = self.x_at(start), self.x_at(end)
            if right >= 0 and left <= width:
                painter.fillRect(QRectF(left, 0, right - left, wave_height), verified)

        loop = self._selection() or self.loop
        if loop is not None:
            soft = QColor(t.accent)
            soft.setAlpha(50)
            left, right = self.x_at(loop[0]), self.x_at(loop[1])
            painter.fillRect(QRectF(left, 0, right - left, wave_height), soft)

        if self._peaks:
            painter.setPen(QColor(t.accent))
            step = self._envelope.step_ms if self._envelope is not None else 10
            scale = self.effective_ms_per_px()
            count = len(self._peaks)
            for x in range(width):
                first = int((self.view_start_ms + x * scale) / step)
                last = max(
                    first + 1, int((self.view_start_ms + (x + 1) * scale) / step)
                )
                if first >= count:
                    break
                peak = max(self._peaks[first : min(last, count)]) * self._scale
                half = max(0.5, peak * (middle - 1))
                painter.drawLine(QPointF(x, middle - half), QPointF(x, middle + half))
        else:
            painter.setPen(QColor(t.border))
            painter.drawLine(QPointF(0, middle), QPointF(width, middle))

        strip_top = height - SEGMENT_STRIP_PX
        for start, end, confidence in self.segments:
            left, right = self.x_at(start), self.x_at(end)
            if right < 0 or left > width:
                continue
            color = QColor(t.success if confidence >= LOW_CONFIDENCE else t.warning)
            painter.fillRect(
                QRectF(left, strip_top, max(1.0, right - left - 1), SEGMENT_STRIP_PX),
                color,
            )

        for start, end in self.verified:
            left, right = self.x_at(start), self.x_at(end)
            if right >= 0 and left <= width:
                painter.fillRect(
                    QRectF(left, 0, right - left, VERIFIED_STRIP_PX), QColor(t.success)
                )

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
        painter.drawLine(QPointF(cursor_x, 0), QPointF(cursor_x, height))
        painter.end()

    # --- mysz -----------------------------------------------------------------

    def _selection(self) -> tuple[int, int] | None:
        if self._press_x is None or self._drag_x is None:
            return None
        a, b = sorted((self.ms_at(self._press_x), self.ms_at(self._drag_x)))
        return (a, b) if b > a else None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.duration_ms:
            self._press_x = event.position().x()
            self._drag_x = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_x is not None:
            x = event.position().x()
            if self._drag_x is not None or abs(x - self._press_x) > DRAG_THRESHOLD_PX:
                self._drag_x = x
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_x is not None:
            selection = self._selection()
            press = self._press_x
            self._press_x = self._drag_x = None
            if selection is not None:
                self.loop_requested.emit(*selection)
            elif not self._dragging:
                self.seek_requested.emit(self.ms_at(press))
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


class WaveformPanel(QWidget):
    """Zwijana fala: nagłówek z postępem, widok i pasek przewijania."""

    expanded_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("waveform_panel")
        self.toggle = QToolButton()
        self.toggle.setObjectName("waveform_toggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setText(tr("waveform.title"))
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.setToolTip(tr("waveform.toggle.tooltip"))
        self.status_label = QLabel()
        set_props(self.status_label, role="muted")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle)
        header.addWidget(self.status_label, stretch=1)
        self.view = WaveformView()
        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self.view)
        layout.addWidget(self.scrollbar)
        self.toggle.toggled.connect(self._on_toggled)
        self.view.view_changed.connect(self._sync_scrollbar)
        self.scrollbar.valueChanged.connect(
            lambda value: self.view.scroll_to(float(value))
        )

    @property
    def expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self.toggle.isChecked():
            self.toggle.setChecked(expanded)
        else:
            self._apply_expanded(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        self._apply_expanded(expanded)
        self.expanded_changed.emit(expanded)

    def _apply_expanded(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.view.setVisible(expanded)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        view = self.view
        start, end = view.visible_range_ms()
        span = int(end - start)
        zoomed = self.expanded and view.duration_ms > span > 0
        self.scrollbar.setVisible(zoomed)
        if zoomed:
            self.scrollbar.blockSignals(True)
            self.scrollbar.setRange(0, max(0, view.duration_ms - span))
            self.scrollbar.setPageStep(span)
            self.scrollbar.setSingleStep(max(1, span // 10))
            self.scrollbar.setValue(int(start))
            self.scrollbar.blockSignals(False)


class WaveformController(QObject):
    """Fala dla bieżącego nagrania: obliczenie w tle i powiązanie z odtwarzaczem."""

    def __init__(
        self,
        player: AudioPlayer,
        player_bar: PlayerBar,
        markers: Callable[[], list[int]],
        on_expanded_changed: Callable[[bool], None],
        parent: QObject | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.panel = WaveformPanel()
        self.panel.setVisible(False)
        self.view = self.panel.view
        self._player = player
        self._bar = player_bar
        self._markers = markers
        self._cache_dir = cache_dir
        self._thread: EnvelopeThread | None = None
        self._threads: set[EnvelopeThread] = set()
        self._path: Path | None = None
        player_bar.set_waveform(self.panel)
        player.position_changed.connect(self.view.set_position)
        player.duration_changed.connect(self.view.set_duration)
        player.loop_changed.connect(lambda _loop: self.refresh_loop())
        player_bar.loop_points_changed.connect(self.refresh_loop)
        player_bar.media_available_changed.connect(self._on_media_available)
        self.view.seek_requested.connect(self._on_seek)
        self.view.loop_requested.connect(self._on_loop)
        self.panel.expanded_changed.connect(on_expanded_changed)

    # --- nagranie -------------------------------------------------------------

    def _on_media_available(self, available: bool) -> None:
        path = self._player.source_path
        if not available or path is None:
            self.clear()
            return
        self.panel.setVisible(True)
        self.view.set_duration(self._player.duration_ms)
        self.refresh_loop()
        self.refresh_markers()
        if path != self._path or self.view.envelope is None:
            self.load(path)

    def load(self, path: Path) -> None:
        """Liczy (albo czyta z cache) obwiednię nagrania w tle."""
        self._cancel()
        self._path = path
        self.view.set_envelope(None)
        self.panel.status_label.setText(tr("waveform.progress", percent=0))
        thread = EnvelopeThread(path, self._cache_dir)
        self._threads.add(thread)
        self._thread = thread
        thread.progressed.connect(self._on_progress)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def clear(self) -> None:
        self._cancel()
        self._path = None
        self.view.set_envelope(None)
        self.view.set_duration(0)
        self.view.segments = []
        self.panel.status_label.setText("")
        self.panel.setVisible(False)

    def _cancel(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.requestInterruption()

    def _on_progress(self, fraction: float) -> None:
        if self.sender() is self._thread:
            self.panel.status_label.setText(
                tr("waveform.progress", percent=int(fraction * 100))
            )

    def _on_thread_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, EnvelopeThread):
            return
        thread.wait()
        self._threads.discard(thread)
        thread.deleteLater()
        if thread is not self._thread:
            return
        self._thread = None
        self.view.set_envelope(thread.envelope)
        self.panel.status_label.setText(
            "" if thread.envelope is not None else tr("waveform.failed")
        )

    @property
    def is_busy(self) -> bool:
        return self._thread is not None

    def shutdown(self) -> None:
        """Przerywa wątki i czeka na nie (zamknięcie okna)."""
        self._cancel()
        for thread in list(self._threads):
            thread.requestInterruption()
            thread.wait()

    # --- nakładki -------------------------------------------------------------

    def set_segments(self, segments: list[SegmentSpan]) -> None:
        self.view.segments = segments
        self.view.update()

    def set_verified(self, ranges: Sequence[tuple[int, int]]) -> None:
        self.view.verified = list(ranges)
        self.view.update()

    def refresh_markers(self) -> None:
        self.view.markers = self._markers()
        self.view.update()

    def refresh_loop(self) -> None:
        self.view.loop = self._player.loop_range or self._bar.loop_points()
        self.view.update()

    # --- interakcja -------------------------------------------------------------

    def _on_seek(self, position_ms: int) -> None:
        self._player.set_position(position_ms)

    def _on_loop(self, start_ms: int, end_ms: int) -> None:
        self._bar.set_loop_points(start_ms, end_ms)
        self.refresh_loop()


def segment_spans(segments: Sequence[SegmentResult]) -> list[SegmentSpan]:
    """Segmenty ASR jako paski fali (ms i pewność)."""
    return [
        (round(s.start_s * 1000), round(s.end_s * 1000), s.confidence) for s in segments
    ]


__all__ = [
    "EnvelopeThread",
    "WaveformController",
    "WaveformPanel",
    "WaveformView",
    "segment_spans",
]
