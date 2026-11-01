"""Fala dźwiękowa pod suwakiem odtwarzacza (faza 11, propozycja 6, ACC-50).

- ``EnvelopeThread`` liczy obwiednię w tle: suma SHA-256 nagrania → cache
  → dekodowanie PyAV (``audio/envelope.py``), z postępem i przerwaniem przy
  zmianie nagrania.
- ``WaveformView`` (``ui/waveform_view.py``) rysuje falę z nakładkami.
- ``WaveformPanel`` to zwijany nagłówek z postępem i pokryciem transkrypcji,
  widok, miniatura całego nagrania (``ui/coverage_overview.py``), pasek
  przewijania i zwijany spektrogram (``ui/spectrogram_view.py``).
- ``WaveformController`` łączy panel z odtwarzaczem, panelem ASR, kotwicami
  tekstu i spektrogramem (``ui/spectrogram_controller.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollBar,
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
    silent_ranges,
)
from transkryptor.audio.player import AudioPlayer
from transkryptor.fileio import file_sha256
from transkryptor.i18n import tr
from transkryptor.ui.coverage_overview import CoverageOverview
from transkryptor.ui.player_bar import PlayerBar
from transkryptor.ui.spectrogram_controller import SpectrogramController
from transkryptor.ui.spectrogram_view import SpectrogramPanel
from transkryptor.ui.theme import set_props
from transkryptor.ui.waveform_view import SegmentSpan, WaveformView

logger = logging.getLogger(__name__)


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
        # Pokrycie transkrypcji tekstem (``ui/coverage_controller.py``).
        self.coverage_label = QLabel()
        self.coverage_label.setObjectName("coverage_label")
        set_props(self.coverage_label, role="muted")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle)
        header.addWidget(self.status_label, stretch=1)
        header.addWidget(self.coverage_label)
        self.view = WaveformView()
        self.overview = CoverageOverview()
        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.setVisible(False)
        self.spectrogram = SpectrogramPanel()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self.view)
        layout.addWidget(self.overview)
        layout.addWidget(self.scrollbar)
        layout.addWidget(self.spectrogram)
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
        for widget in (self.view, self.overview, self.spectrogram):
            widget.setVisible(expanded)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        view = self.view
        start, end = view.visible_range_ms()
        span = int(end - start)
        zoomed = self.expanded and view.duration_ms > span > 0
        self.scrollbar.setVisible(zoomed)
        self.overview.set_window((int(start), int(end)) if zoomed else None)
        if zoomed:
            self.scrollbar.blockSignals(True)
            self.scrollbar.setRange(0, max(0, view.duration_ms - span))
            self.scrollbar.setPageStep(span)
            self.scrollbar.setSingleStep(max(1, span // 10))
            self.scrollbar.setValue(int(start))
            self.scrollbar.blockSignals(False)


class WaveformController(QObject):
    """Fala dla bieżącego nagrania: obliczenie w tle i powiązanie z odtwarzaczem."""

    # Obwiednia nagrania gotowa albo usunięta (np. zmienia się wykryta cisza).
    envelope_changed = Signal()

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
        self.spectrogram = SpectrogramController(
            self.panel.spectrogram, player, self.view, self._loop_range, self
        )
        player_bar.set_waveform(self.panel)
        overview = self.panel.overview
        player.position_changed.connect(self.view.set_position)
        player.position_changed.connect(overview.set_position)
        player.duration_changed.connect(self.view.set_duration)
        player.duration_changed.connect(overview.set_duration)
        player.loop_changed.connect(lambda _loop: self.refresh_loop())
        player_bar.loop_points_changed.connect(self.refresh_loop)
        player_bar.media_available_changed.connect(self._on_media_available)
        for source in (self.view, self.panel.spectrogram.view):
            source.seek_requested.connect(self._on_seek)
            source.loop_requested.connect(self._on_loop)
        overview.seek_requested.connect(self._on_seek)
        self.panel.expanded_changed.connect(on_expanded_changed)

    # --- nagranie -------------------------------------------------------------

    def _on_media_available(self, available: bool) -> None:
        path = self._player.source_path
        if not available or path is None:
            self.clear()
            return
        self.panel.setVisible(True)
        self.view.set_duration(self._player.duration_ms)
        self.panel.overview.set_duration(self._player.duration_ms)
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
        self.envelope_changed.emit()
        self.view.set_duration(0)
        self.panel.overview.set_duration(0)
        self.view.segments = []
        self.spectrogram.clear()
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
        self.envelope_changed.emit()
        self.panel.status_label.setText(
            "" if thread.envelope is not None else tr("waveform.failed")
        )

    @property
    def is_busy(self) -> bool:
        return self._thread is not None

    def shutdown(self) -> None:
        """Przerywa wątki i czeka na nie (zamknięcie okna)."""
        self.spectrogram.shutdown()
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

    def silence(self) -> tuple[tuple[int, int], ...]:
        """Cisza wykryta w obwiedni nagrania (pusta, dopóki fala się liczy)."""
        envelope = self.view.envelope
        return silent_ranges(envelope) if envelope is not None else ()

    def _loop_range(self) -> tuple[int, int] | None:
        return self._player.loop_range or self._bar.loop_points()

    def refresh_loop(self) -> None:
        self.view.loop = self._loop_range()
        self.view.update()
        self.spectrogram.schedule()

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
    "segment_spans",
]
