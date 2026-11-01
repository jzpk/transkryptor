"""Licznik czasu aktywnej pracy nad projektem.

Czas rośnie tylko przy aktywności w programie: edycji tekstu, ruchu kursora
w edytorze (klawiatura, kliknięcie) albo odtwarzaniu nagrania (transkrybent
słucha). Źródła aktywności to sygnały podane przez :meth:`watch` - bez
filtra zdarzeń całej aplikacji, który spowalniałby każde zdarzenie Qt.
Przerwa między kolejnymi oznakami aktywności jest doliczana, gdy
nie przekracza ``IDLE_LIMIT_S`` - dłuższa przerwa to bezczynność i nie
liczy się do czasu pracy. Wynik to ``WorkLog`` (``document/work_log.py``)
zapisywany w pliku projektu; pierwsza aktywność dnia zapamiętuje pokrycie
nagrania tekstem, od którego liczony jest postęp celu dziennego.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QObject, QTimer, SignalInstance

from transkryptor.audio.player import AudioPlayer
from transkryptor.document.work_log import WorkLog

# Dłuższa przerwa bez aktywności nie jest czasem pracy.
IDLE_LIMIT_S = 120.0
# Co tyle odtwarzanie nagrania liczy się jako aktywność.
PLAYBACK_TICK_MS = 15_000


class WorkTimeTracker(QObject):
    """Czas aktywnej pracy z limitem bezczynności."""

    def __init__(
        self,
        player: AudioPlayer,
        coverage_ms: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], str] = lambda: date.today().isoformat(),
    ) -> None:
        super().__init__(player)
        self._player = player
        self._coverage_ms = coverage_ms
        # Zegar (sekundy); testy podstawiają własny.
        self.clock = clock
        self._today = today
        self._log = WorkLog()
        self._last: float | None = None
        self._pending = 0.0
        self._playback = QTimer(self)
        self._playback.setInterval(PLAYBACK_TICK_MS)
        self._playback.timeout.connect(self._on_playback_tick)
        self._playback.start()

    @property
    def log(self) -> WorkLog:
        return self._log

    def watch(self, *signals: SignalInstance) -> None:
        """Sygnały oznaczające pracę użytkownika (np. zmiana tekstu)."""
        for signal in signals:
            signal.connect(lambda *_args: self.register_activity())

    def register_activity(self) -> None:
        """Oznaka pracy: dolicza czas od poprzedniej, jeśli to nie bezczynność."""
        now = self.clock()
        last, self._last = self._last, now
        if last is None:
            self._start_day()
            return
        elapsed = now - last
        if not 0 < elapsed <= IDLE_LIMIT_S:
            return
        self._pending += elapsed
        seconds = int(self._pending)
        if seconds:
            self._pending -= seconds
            # Wpis dnia (z pokryciem nagrania) powstaje tylko raz dziennie.
            self._start_day()
            self._log = self._log.add(seconds, self._today())

    def entries(self) -> WorkLog:
        """Czas pracy do zapisu w projekcie (z długością bieżącego nagrania)."""
        duration = self._player.duration_ms if self._player.source_path else None
        return self._log.with_duration(duration)

    def restore(self, log: WorkLog) -> None:
        self._log = log
        self._reset_activity()

    def clear(self) -> None:
        self.restore(WorkLog())

    def _start_day(self) -> None:
        today = self._today()
        if self._log.day(today) is None:
            self._log = self._log.start_day(today, self._coverage_ms())

    def _reset_activity(self) -> None:
        self._last = None
        self._pending = 0.0

    def _on_playback_tick(self) -> None:
        if self._player.is_playing:
            self.register_activity()
