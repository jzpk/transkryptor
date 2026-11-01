"""Mapa pokrycia transkrypcji na fali i przejścia między lukami.

``CoverageController`` liczy (z przerwą po zmianach) fragmenty nagrania
powiązane z tekstem - tę samą definicję co okno „Statystyki projektu”
(``document/progress.covered_ranges``) - i luki bez tekstu
(``document/coverage.py``; cisza z obwiedni fali nie jest luką). Pokazuje
je na fali i w miniaturze całego nagrania, a w nagłówku fali procent
pokrycia i liczbę luk. Akcje „Następna luka” / „Poprzednia luka” (skróty
w zakładce „Skróty”) przewijają nagranie do początku luki i ustawiają
kursor tekstu w miejscu, gdzie brakuje transkrypcji.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from transkryptor.audio.player import AudioPlayer
from transkryptor.document.coverage import gap_target, transcription_gaps
from transkryptor.document.progress import format_percent, total_ms
from transkryptor.document.verification import clipped
from transkryptor.i18n import tr
from transkryptor.ui.player_bar import format_ms
from transkryptor.ui.waveform import WaveformController

Range = tuple[int, int]

# Przerwa od ostatniej zmiany tekstu lub kotwic do przeliczenia mapy.
REFRESH_DEBOUNCE_MS = 400


class CoverageController(QObject):
    """Pokrycie nagrania tekstem, luki i przejścia do luk."""

    def __init__(
        self,
        waveform: WaveformController,
        player: AudioPlayer,
        covered: Callable[[], Sequence[Range]],
        cursor_to_time: Callable[[int], object],
        show_status: Callable[[str], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._waveform = waveform
        self._player = player
        self._covered = covered
        self._cursor_to_time = cursor_to_time
        self._show_status = show_status
        self._parent = parent
        self.gaps: tuple[Range, ...] = ()
        self.ratio: float | None = None
        self._locked = False
        self.next_action = self._action("coverage.action.next", True)
        self.previous_action = self._action("coverage.action.previous", False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        waveform.envelope_changed.connect(self.schedule)
        player.duration_changed.connect(lambda _duration: self.schedule())
        self.refresh()

    def _action(self, key: str, forward: bool) -> QAction:
        action = QAction(tr(key), self._parent)
        action.triggered.connect(lambda _checked=False: self.go_to(forward))
        self._parent.addAction(action)
        return action

    @property
    def actions(self) -> tuple[QAction, ...]:
        return (self.next_action, self.previous_action)

    @property
    def _duration(self) -> int:
        return self._player.duration_ms if self._player.source_path else 0

    def schedule(self) -> None:
        """Tekst, kotwice albo nagranie się zmieniły - przeliczenie po przerwie."""
        self._timer.start()

    def refresh(self) -> None:
        self._timer.stop()
        duration = self._duration
        panel = self._waveform.panel
        if duration <= 0:
            self.gaps, self.ratio = (), None
            self._waveform.view.set_coverage([], [])
            panel.overview.set_coverage([], [])
            panel.coverage_label.setText("")
            self._update_actions()
            return
        covered = clipped(self._covered(), duration)
        self.gaps = transcription_gaps(covered, duration, self._waveform.silence())
        self.ratio = min(1.0, total_ms(covered) / duration)
        self._waveform.view.set_coverage(covered, self.gaps)
        panel.overview.set_coverage(covered, self.gaps)
        panel.coverage_label.setText(
            tr(
                "coverage.label",
                percent=format_percent(self.ratio),
                gaps=len(self.gaps),
            )
        )
        panel.coverage_label.setToolTip(
            tr(
                "coverage.label.tooltip",
                covered=format_ms(total_ms(covered)),
                duration=format_ms(duration),
                gap_time=format_ms(total_ms(self.gaps)),
            )
        )
        self._update_actions()

    def go_to(self, forward: bool = True) -> bool:
        """Przewija nagranie i kursor tekstu do następnej/poprzedniej luki."""
        if self._timer.isActive():
            self.refresh()
        if self._duration <= 0:
            self._show_status(tr("sync.no_media"))
            return False
        target = gap_target(self.gaps, self._player.position_ms, forward)
        if target is None:
            self._show_status(tr("coverage.no_gaps"))
            return False
        start, wrapped = target
        end = next(b for a, b in self.gaps if a == start)
        self._player.set_position(start)
        self._waveform.view.show_range(start, end)
        self._cursor_to_time(start)
        index = [a for a, _b in self.gaps].index(start) + 1
        message = tr(
            "coverage.gap",
            start=format_ms(start),
            end=format_ms(end),
            index=index,
            count=len(self.gaps),
        )
        if wrapped:
            message = f"{message} - {tr('sync.uncertain.wrapped')}"
        self._show_status(message)
        return True

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self._update_actions()

    def _update_actions(self) -> None:
        enabled = self._duration > 0 and not self._locked
        for action in self.actions:
            action.setEnabled(enabled)
