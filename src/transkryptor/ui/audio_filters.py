"""Filtry odsłuchu w oknie: kopia nagrania przygotowywana w tle.

``FilterThread`` zapisuje przefiltrowaną kopię nagrania
(``audio/processing.py``), a ``AudioFilterController`` pilnuje, by
odtwarzacz grał kopię pasującą do bieżącego nagrania i wybranych filtrów:

- bez filtrów odtwarzany jest oryginał;
- gotowa kopia z pamięci podręcznej jest używana od razu;
- brakująca powstaje w tle (postęp w karcie odtwarzacza), a do tego czasu
  gra oryginał - po podmianie pozycja i odtwarzanie trwają dalej;
- zmiana nagrania albo filtrów przerywa przygotowanie nieaktualnej kopii;
- błąd przetwarzania zostawia oryginał z komunikatem w karcie.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from transkryptor.audio import processing
from transkryptor.audio.player import AudioPlayer
from transkryptor.audio.processing import (
    AudioFilters,
    cache_path,
    process_audio,
    prune_cache,
    touch,
)
from transkryptor.i18n import tr

logger = logging.getLogger(__name__)


class FilterThread(QThread):
    """Przefiltrowana kopia nagrania w tle; ``ok`` - kopia gotowa."""

    progressed = Signal(float)

    def __init__(
        self,
        source: Path,
        target: Path,
        filters: AudioFilters,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.target = target
        self.filters = filters
        self.ok = False
        self._percent = -1

    def run(self) -> None:
        try:
            process_audio(
                self.source,
                self.target,
                self.filters,
                should_cancel=self.isInterruptionRequested,
                on_progress=self._report,
            )
        except InterruptedError:
            return
        except Exception:  # noqa: BLE001 - bez filtrów gra oryginał
            logger.warning("Playback filters could not be applied", exc_info=True)
            return
        self.ok = True

    def _report(self, fraction: float) -> None:
        percent = int(fraction * 100)
        if percent != self._percent:
            self._percent = percent
            self.progressed.emit(fraction)


class AudioFilterController(QObject):
    """Kopia nagrania z filtrami odsłuchu dla odtwarzacza."""

    status_changed = Signal(str)  # pusty - brak komunikatu

    def __init__(
        self,
        player: AudioPlayer,
        parent: QObject | None = None,
        cache_dir: Callable[[], Path] | None = None,
    ) -> None:
        super().__init__(parent)
        self._player = player
        # Odczyt przy każdym użyciu - testy podmieniają katalog cache.
        self._cache_dir = cache_dir or (lambda: processing.playback_cache_dir())
        self._filters = AudioFilters()
        self._thread: FilterThread | None = None
        self._threads: set[FilterThread] = set()

    @property
    def filters(self) -> AudioFilters:
        return self._filters

    @property
    def is_busy(self) -> bool:
        return self._thread is not None

    def set_filters(self, filters: AudioFilters) -> None:
        if filters != self._filters:
            self._filters = filters
            self.refresh()

    def refresh(self) -> None:
        """Dopasowuje odtwarzany plik do nagrania i filtrów (np. nowe nagranie)."""
        self._cancel()
        source = self._player.source_path
        if source is None or not self._filters.active:
            self._player.set_playback_file(None)
            self.status_changed.emit("")
            return
        directory = self._cache_dir()
        try:
            target = cache_path(source, self._filters, directory)
        except OSError:
            self._player.set_playback_file(None)
            self.status_changed.emit(tr("player.sound.failed"))
            return
        if target.is_file():
            touch(target)
            self._player.set_playback_file(target)
            self.status_changed.emit("")
            return
        # Do czasu przygotowania kopii gra oryginał (bez starych filtrów).
        self._player.set_playback_file(None)
        self.status_changed.emit(tr("player.sound.progress", percent=0))
        thread = FilterThread(source, target, self._filters)
        self._threads.add(thread)
        self._thread = thread
        thread.progressed.connect(self._on_progress)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def _cancel(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.requestInterruption()

    def _on_progress(self, fraction: float) -> None:
        if self.sender() is self._thread:
            self.status_changed.emit(
                tr("player.sound.progress", percent=int(fraction * 100))
            )

    def _on_thread_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, FilterThread):
            return
        thread.wait()
        self._threads.discard(thread)
        thread.deleteLater()
        if thread is not self._thread:
            return
        self._thread = None
        current = self._player.source_path
        if not thread.ok or current is None or current != thread.source:
            self.status_changed.emit("" if thread.ok else tr("player.sound.failed"))
            return
        prune_cache(thread.target.parent, keep=thread.target)
        self._player.set_playback_file(thread.target)
        self.status_changed.emit("")

    def shutdown(self) -> None:
        """Przerywa wątki i czeka na nie (zamknięcie okna)."""
        self._cancel()
        for thread in list(self._threads):
            thread.requestInterruption()
            thread.wait()
