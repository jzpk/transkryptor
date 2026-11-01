"""Spektrogram fragmentu: wybór zakresu i liczenie w tle.

``SpectrogramController`` pokazuje spektrogram pętli A-B, a bez pętli -
widocznego zakresu powiększonej fali. Zakres dłuższy niż
``audio.spectrogram.MAX_RANGE_MS`` nie jest liczony (panel prosi o krótszy
fragment), więc godzinne nagranie nie obciąża programu. Liczenie
(``SpectrogramThread``) rusza po krótkiej przerwie od ostatniej zmiany
zakresu i jest przerywane, gdy zakres zmieni się w trakcie; zwinięty panel
niczego nie liczy. Odtwarzanie przesuwa kursor spektrogramu, a gdy fala
przewija się za kursorem, spektrogram liczy się dla nowego widoku.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer

from transkryptor.audio.player import AudioPlayer
from transkryptor.audio.spectrogram import (
    MAX_RANGE_MS,
    Spectrogram,
    SpectrogramOptions,
    is_too_long,
    spectrogram_for,
)
from transkryptor.i18n import tr
from transkryptor.ui.spectrogram_view import SpectrogramPanel
from transkryptor.ui.waveform_view import WaveformView

logger = logging.getLogger(__name__)

# Przerwa od ostatniej zmiany zakresu do startu liczenia.
DEBOUNCE_MS = 250

Request = tuple[Path, int, int, SpectrogramOptions]


class SpectrogramThread(QThread):
    """Spektrogram jednego zakresu; ``result`` to wynik albo None."""

    def __init__(self, request: Request, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.request = request
        self.result: Spectrogram | None = None

    def run(self) -> None:
        path, start, end, options = self.request
        try:
            self.result = spectrogram_for(
                path, start, end, options, self.isInterruptionRequested
            )
        except InterruptedError:
            return
        except Exception:  # spektrogram jest pomocniczy; brak to nie błąd
            logger.warning("Spectrogram could not be computed", exc_info=True)


class SpectrogramController(QObject):
    """Zakres spektrogramu, liczenie w tle i powiązanie z odtwarzaczem."""

    def __init__(
        self,
        panel: SpectrogramPanel,
        player: AudioPlayer,
        wave: WaveformView,
        loop: Callable[[], tuple[int, int] | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.panel = panel
        self._player = player
        self._wave = wave
        self._loop = loop
        self.options = SpectrogramOptions()
        self._shown: Request | None = None
        self._thread: SpectrogramThread | None = None
        self._threads: set[SpectrogramThread] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        player.position_changed.connect(panel.view.set_position)
        wave.view_changed.connect(self.schedule)
        panel.expanded_changed.connect(lambda _expanded: self.schedule())

    def apply_options(self, options: SpectrogramOptions) -> None:
        if options != self.options:
            self.options = options
            self.schedule()

    def schedule(self) -> None:
        """Zakres mógł się zmienić - liczenie po przerwie (debounce)."""
        self.panel.view.set_loop(self._loop())
        self._timer.start()

    def target_range(self) -> tuple[int, int] | None:
        """Pętla A-B albo widoczny zakres fali (None - brak albo za długi)."""
        loop = self._loop()
        if loop is not None and loop[1] > loop[0]:
            return loop if not is_too_long(*loop) else None
        if not self._wave.duration_ms:
            return None
        start, end = self._wave.visible_range_ms()
        span = (int(start), int(min(end, self._wave.duration_ms)))
        return span if span[1] > span[0] and not is_too_long(*span) else None

    def refresh(self) -> None:
        """Liczy spektrogram bieżącego zakresu (gdy panel jest rozwinięty)."""
        path = self._player.source_path
        if not self.panel.expanded or path is None:
            return
        span = self.target_range()
        if span is None:
            self._cancel()
            self._shown = None
            self.panel.view.set_spectrogram(None)
            self.panel.set_status(
                tr("spectrogram.too_long", seconds=MAX_RANGE_MS // 1000)
            )
            return
        request: Request = (path, *span, self.options)
        running = self._thread.request if self._thread is not None else None
        if request in (self._shown, running):
            return
        self._cancel()
        self.panel.set_status(tr("spectrogram.computing"))
        thread = SpectrogramThread(request)
        self._threads.add(thread)
        self._thread = thread
        thread.finished.connect(self._on_finished)
        thread.start()

    def clear(self) -> None:
        self._cancel()
        self._shown = None
        self.panel.view.set_spectrogram(None)
        self.panel.set_status("")

    @property
    def is_busy(self) -> bool:
        return self._thread is not None

    def shutdown(self) -> None:
        self._timer.stop()
        self._cancel()
        for thread in list(self._threads):
            thread.requestInterruption()
            thread.wait()

    def _cancel(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.requestInterruption()

    def _on_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, SpectrogramThread):
            return
        thread.wait()
        self._threads.discard(thread)
        thread.deleteLater()
        if thread is not self._thread:
            return
        self._thread = None
        result = thread.result
        self._shown = thread.request if result is not None else None
        self.panel.view.set_spectrogram(result)
        self.panel.view.set_position(self._player.position_ms)
        self.panel.set_status("" if result is not None else tr("spectrogram.failed"))
