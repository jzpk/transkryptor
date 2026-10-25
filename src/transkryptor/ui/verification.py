"""Postęp weryfikacji nagrania w oknie (``document/verification.py``).

``VerificationController`` przechowuje sprawdzone zakresy nagrania
bieżącego projektu i obsługuje:

- „Oznacz jako sprawdzone do bieżącego miejsca” (skrót, domyślnie F9) -
  luka przed pozycją odtwarzania staje się sprawdzona;
- „Przejdź do niesprawdzonego miejsca” (Shift+F9) - odtwarzacz i kursor
  tekstu wracają tam, gdzie skończyła się weryfikacja;
- oznaczenie zaznaczonego tekstu jako sprawdzonego albo niesprawdzonego
  (menu kontekstowe edytora; czas z kotwic tekstu);
- przycisk z procentem sprawdzonego nagrania w karcie odtwarzacza i tło
  sprawdzonych fragmentów na fali dźwiękowej.

Zakresy należą do projektu (``ProjectState.verified``); zmiana nagrania
je czyści.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from transkryptor.audio.player import AudioPlayer
from transkryptor.document import verification
from transkryptor.document.verification import MIN_GAP_MS, Range
from transkryptor.i18n import tr
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.player_bar import PlayerBar, format_ms
from transkryptor.ui.sync_controller import SyncController


class VerificationController(QObject):
    """Sprawdzone zakresy nagrania: oznaczanie, przejścia i postęp."""

    ranges_changed = Signal()  # każda zmiana (także odczyt projektu)
    edited = Signal()  # zmiana przez użytkownika - projekt niezapisany

    def __init__(
        self,
        editor: TranscriptionEditor,
        player: AudioPlayer,
        player_bar: PlayerBar,
        sync: SyncController,
        show_status: Callable[[str], None],
        dialog_parent: QWidget,
    ) -> None:
        super().__init__(dialog_parent)
        self._editor = editor
        self._player = player
        self._bar = player_bar
        self._sync = sync
        self._show_status = show_status
        self._parent = dialog_parent
        self._ranges: tuple[Range, ...] = ()
        self._locked = False
        self.mark_action = self._action("verification.action.mark", self.mark_until)
        self.next_action = self._action("verification.action.next", self.go_to_next)
        self.clear_action = self._action(
            "verification.action.clear", self.clear_with_confirmation
        )
        player_bar.set_verification_actions(
            [self.mark_action, self.next_action, None, self.clear_action]
        )
        editor.context_menu_extenders.append(self.extend_context_menu)
        player_bar.media_available_changed.connect(lambda _media: self.refresh())
        player.duration_changed.connect(lambda _duration: self.refresh())
        self.refresh()

    def _action(self, key: str, handler: Callable[[], object]) -> QAction:
        action = QAction(tr(key), self._parent)
        action.triggered.connect(lambda _checked=False: handler())
        self._parent.addAction(action)
        return action

    @property
    def actions(self) -> tuple[QAction, ...]:
        return (self.mark_action, self.next_action, self.clear_action)

    # --- stan ---------------------------------------------------------------

    @property
    def ranges(self) -> tuple[Range, ...]:
        return self._ranges

    def entries(self) -> tuple[Range, ...]:
        """Zakresy do zapisu projektu."""
        return self._ranges

    def restore(self, ranges: Iterable[Range]) -> None:
        self._ranges = verification.normalized(ranges)
        self.refresh()
        self.ranges_changed.emit()

    def clear(self) -> None:
        """Nowy dokument albo inne nagranie: nic nie jest sprawdzone."""
        self.restore(())

    def _set(self, ranges: tuple[Range, ...]) -> bool:
        if ranges == self._ranges:
            return False
        self._ranges = ranges
        self.refresh()
        self.ranges_changed.emit()
        self.edited.emit()
        return True

    @property
    def _duration(self) -> int:
        return self._player.duration_ms if self._bar.has_media else 0

    @property
    def coverage(self) -> float:
        return verification.coverage(self._ranges, self._duration)

    # --- akcje ----------------------------------------------------------------

    def _has_media(self) -> bool:
        if self._player.source_path is None or not self._bar.has_media:
            self._show_status(tr("sync.no_media"))
            return False
        return True

    def mark_until(self) -> bool:
        """Sprawdzone od końca poprzedniego sprawdzonego fragmentu do pozycji."""
        if not self._has_media():
            return False
        duration = self._duration
        position = self._player.position_ms
        # Ułamek sekundy przed końcem nagrania to już koniec nagrania.
        if duration - position < MIN_GAP_MS:
            position = duration
        if not self._set(verification.mark_until(self._ranges, position)):
            self._show_status(tr("verification.already"))
            return False
        self._show_status(
            tr(
                "verification.marked",
                time=format_ms(position),
                percent=self._percent(),
            )
        )
        return True

    def go_to_next(self) -> bool:
        """Odtwarzacz i kursor tekstu w niesprawdzonym miejscu (bez odtwarzania)."""
        if not self._has_media():
            return False
        target = verification.next_gap(
            self._ranges, self._player.position_ms, self._duration
        )
        if target is None:
            self._show_status(tr("verification.done"))
            return False
        start, wrapped = target
        self._player.set_position(start)
        self._sync.cursor_to_time(start)
        self._editor.setFocus()
        message = tr("verification.next", time=format_ms(start))
        if wrapped:
            message = f"{message} - {tr('sync.uncertain.wrapped')}"
        self._show_status(message)
        return True

    def mark_selection(self, verified: bool = True) -> bool:
        """Zaznaczony tekst (czas z kotwic) jako sprawdzony albo niesprawdzony."""
        span = self._selection_span()
        if span is None:
            self._show_status(tr("verification.no_time"))
            return False
        start, end = span
        ranges = (
            verification.add(self._ranges, start, end)
            if verified
            else verification.remove(self._ranges, start, end)
        )
        self._set(ranges)
        key = "verification.selection_marked" if verified else "verification.unmarked"
        self._show_status(tr(key, start=format_ms(start), end=format_ms(end)))
        return True

    def clear_with_confirmation(self) -> bool:
        if not self._ranges:
            return False
        answer = QMessageBox.question(
            self._parent,
            tr("verification.clear.title"),
            tr("verification.clear.text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        return self._set(())

    def _selection_span(self) -> tuple[int, int] | None:
        cursor = self._editor.textCursor()
        if not cursor.hasSelection():
            return None
        start, end = self._editor.selection_range(cursor)
        return self._sync.time_span(start, end)

    def extend_context_menu(self, menu: QMenu, _position: int) -> None:
        span = self._selection_span()
        if span is None:
            return
        menu.addSeparator()
        mark = menu.addAction(tr("verification.action.mark_selection"))
        mark.triggered.connect(lambda _checked=False: self.mark_selection(True))
        if verification.overlaps(self._ranges, *span):
            unmark = menu.addAction(tr("verification.action.unmark_selection"))
            unmark.triggered.connect(lambda _checked=False: self.mark_selection(False))

    # --- prezentacja ----------------------------------------------------------

    def _percent(self) -> int:
        """Procent w dół (99% to jeszcze nie całość), 100% tylko bez luk."""
        duration = self._duration
        if duration > 0 and not verification.gaps(self._ranges, duration):
            return 100
        return min(99, int(self.coverage * 100))

    def refresh(self) -> None:
        duration = self._duration
        enabled = duration > 0 and not self._locked
        for action in (self.mark_action, self.next_action):
            action.setEnabled(enabled)
        self.clear_action.setEnabled(bool(self._ranges) and not self._locked)
        if duration <= 0:
            self._bar.set_verification_progress(None, "")
            return
        covered = verification.covered_ms(self._ranges, duration)
        self._bar.set_verification_progress(
            tr("verification.progress", percent=self._percent()),
            tr(
                "verification.progress.tooltip",
                covered=format_ms(covered),
                duration=format_ms(duration),
            ),
        )

    def set_locked(self, locked: bool) -> None:
        """Na czas transkrypcji ASR akcje są nieaktywne."""
        self._locked = locked
        self.refresh()
