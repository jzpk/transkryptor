"""Tekst powiązany z nagraniem: kotwice czasowe w edytorze (faza 11, REQ-22).

``SyncController`` śledzi kotwice (``document/anchors.py``) kursorami
edytora, które przesuwają się razem z edycją — jak pozycje przeglądu reguł.
Obsługuje:

- ``Ctrl+klik`` i skrót „odtwórz od kursora”: odtwarzanie od kotwicy
  (segment — z wyprzedzeniem z ustawień, znacznik ręczny — dokładnie od
  zapisanego czasu, słowo — w tymczasowej pętli);
- podświetlenie segmentu odpowiadającego pozycji odtwarzania (warstwa
  ``ACTIVE_LAYER``, najwyżej co ``HIGHLIGHT_INTERVAL_MS``) i opcjonalne
  przewijanie edytora za odtwarzaniem;
- ręczne znaczniki czasu (punkty rysowane w tekście, bez wpływu na tekst
  i eksport DOCX);
- niepewne słowa ASR: kropkowane podkreślenie (``UNCERTAIN_LAYER``) słów
  o pewności poniżej progu z ustawień, w widocznej części tekstu; poprawione
  słowo traci podkreślenie.

Kursor segmentu lub słowa, którego tekst usunięto, przestaje być kotwicą.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import QMenu

from transkryptor.audio.player import AudioPlayer
from transkryptor.document.anchors import (
    MANUAL,
    SEGMENT,
    WORD,
    Anchor,
    TimeIndex,
    anchor_at,
)
from transkryptor.i18n import tr
from transkryptor.settings import AsrSettings, PlayerSettings
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import (
    ACTIVE_LAYER,
    UNCERTAIN_LAYER,
    background,
    dotted_underline,
)
from transkryptor.ui.player_bar import PlayerBar, format_ms
from transkryptor.ui.positions import PositionMap
from transkryptor.ui.theme import tokens

# Podświetlenie aktywnego segmentu: najwyżej raz na tyle ms (PERF).
HIGHLIGHT_INTERVAL_MS = 150
# Margines tymczasowej pętli słowa — Whisper ucina granice słów.
WORD_MARGIN_MS = 150
ACTIVE_ALPHA = 45
# Podkreślenia niepewnych słów po edycji lub przewinięciu (debounce).
UNCERTAIN_DEBOUNCE_MS = 200


@dataclass
class TrackedAnchor:
    """Kotwica z kursorem edytora; ``baseline`` — tekst słowa po wstawieniu."""

    anchor: Anchor
    cursor: QTextCursor
    baseline: str | None = None

    @property
    def alive(self) -> bool:
        return self.anchor.source == MANUAL or self.cursor.hasSelection()

    @property
    def edited(self) -> bool:
        return self.anchor.edited or (
            self.baseline is not None and self.cursor.selectedText() != self.baseline
        )


class SyncController(QObject):
    """Kotwice czasowe tekstu, odtwarzanie z tekstu i podświetlenie segmentu."""

    anchors_changed = Signal()  # każda zmiana listy kotwic
    timestamps_edited = Signal()  # użytkownik dodał lub usunął znacznik ręczny

    def __init__(
        self,
        editor: TranscriptionEditor,
        player: AudioPlayer,
        player_bar: PlayerBar,
        settings: Callable[[], PlayerSettings],
        show_status: Callable[[str], None],
        parent: QObject | None = None,
        asr_settings: Callable[[], AsrSettings] = AsrSettings,
    ) -> None:
        super().__init__(parent)
        self._asr_settings = asr_settings
        self._editor = editor
        self._player = player
        self._bar = player_bar
        self._settings = settings
        self._show_status = show_status
        self._items: list[TrackedAnchor] = []
        self._index = TimeIndex([])
        self._active: int | None = None
        self._last_position_ms = 0
        self._throttle = QTimer(self)
        self._throttle.setSingleShot(True)
        self._throttle.setInterval(HIGHLIGHT_INTERVAL_MS)
        self._throttle.timeout.connect(self._update_active)
        self._uncertain_timer = QTimer(self)
        self._uncertain_timer.setSingleShot(True)
        self._uncertain_timer.setInterval(UNCERTAIN_DEBOUNCE_MS)
        self._uncertain_timer.timeout.connect(self.update_uncertain)
        editor.ctrl_clicked.connect(lambda position: self.play_at(position))
        editor.context_menu_extenders.append(self.extend_context_menu)
        editor.tooltip_providers.append(self.tooltip_at)
        editor.document().contentsChanged.connect(self.schedule_uncertain)
        editor.verticalScrollBar().valueChanged.connect(self.schedule_uncertain)
        player.position_changed.connect(self._on_position_changed)

    # --- stan -------------------------------------------------------------

    @property
    def items(self) -> list[TrackedAnchor]:
        return self._items

    def has_anchors(self) -> bool:
        return any(item.alive for item in self._items)

    def clear(self) -> None:
        """Usuwa wszystkie kotwice (nowy dokument, inne nagranie)."""
        had = bool(self._items)
        self._items = []
        self._rebuild()
        if had:
            self.anchors_changed.emit()

    def add_anchors(self, offset: int, anchors: Iterable[Anchor]) -> None:
        """Dodaje kotwice szkicu (pozycje względem ``offset`` w edytorze).

        Tekst słów zapamiętuje :meth:`settle` — po zastosowaniu reguł.
        """
        positions = self._editor.position_map()
        for anchor in anchors:
            self._items.append(self._track(anchor.shifted(offset), positions))
        self._rebuild()
        self.anchors_changed.emit()

    def settle(self) -> None:
        """Kończy wstawianie szkicu (po regułach).

        Zapamiętuje bieżący tekst nowych słów — późniejsza zmiana to poprawka —
        i przestaje rozszerzać segmenty o tekst wpisany tuż za nimi.
        """
        for item in self._items:
            if item.anchor.source == WORD and item.baseline is None:
                item.baseline = item.cursor.selectedText()
            elif item.anchor.source == SEGMENT:
                item.cursor.setKeepPositionOnInsert(True)
        self.update_uncertain()

    def loosen(self) -> None:
        """Przed zastosowaniem propozycji reguły: segmenty obejmą zamianę na końcu."""
        for item in self._items:
            if item.anchor.source == SEGMENT:
                item.cursor.setKeepPositionOnInsert(False)

    def entries(self) -> list[Anchor]:
        """Kotwice z bieżącymi zakresami w tekście (zapis projektu)."""
        positions = self._editor.position_map()
        anchors: list[Anchor] = []
        for item in self._items:
            if not item.alive:
                continue
            start, end = self._editor.selection_range(item.cursor, positions)
            edited = item.anchor.source == WORD and item.edited
            anchors.append(replace(item.anchor, start=start, end=end, edited=edited))
        return anchors

    def restore(self, anchors: Sequence[Anchor]) -> None:
        """Odtwarza kotwice z projektu (tekst edytora już wczytany)."""
        positions = self._editor.position_map()
        length = len(positions.text)
        self._items = [
            self._track(anchor, positions) for anchor in anchors if anchor.end <= length
        ]
        self.settle()
        self._rebuild()
        self.anchors_changed.emit()

    def _track(self, anchor: Anchor, positions: PositionMap) -> TrackedAnchor:
        cursor = self._editor.track_range(anchor.start, anchor.end, positions)
        # Tekst wpisany tuż za kotwicą nie rozszerza jej zakresu, a tekst
        # wpisany w miejscu znacznika punktowego trafia za znacznik (koniec
        # kursora zostaje, przesuwa się tylko jego drugi brzeg — znacznik to
        # zawsze ``selectionStart``). Segment dostaje tę właściwość dopiero
        # w :meth:`settle` — zamiana reguły na jego końcu ma zostać w środku.
        cursor.setKeepPositionOnInsert(anchor.source != SEGMENT)
        return TrackedAnchor(anchor, cursor)

    def _rebuild(self) -> None:
        """Indeks czasu segmentów i znaczniki ręczne po zmianie listy."""
        self._items = [item for item in self._items if item.alive]
        self._index = TimeIndex([item.anchor for item in self._items])
        self._active = None
        self._editor.set_highlight_layer(ACTIVE_LAYER, [])
        self._update_active()
        self._editor.set_point_markers(
            [
                QTextCursor(item.cursor)
                for item in self._items
                if item.anchor.source == MANUAL
            ],
            QColor(tokens().accent),
        )
        self.schedule_uncertain()

    def manual_times_ms(self) -> list[int]:
        """Czasy ręcznych znaczników (dla fali dźwiękowej)."""
        return sorted(
            item.anchor.start_ms for item in self._items if item.anchor.source == MANUAL
        )

    def refresh_theme(self) -> None:
        self._rebuild()

    # --- niepewne słowa ------------------------------------------------------

    def schedule_uncertain(self) -> None:
        if any(item.anchor.source == WORD for item in self._items) or (
            self._editor.highlight_layer(UNCERTAIN_LAYER)
        ):
            self._uncertain_timer.start()

    def _uncertain_items(self, first: int, last: int) -> list[TrackedAnchor]:
        """Niepoprawione niepewne słowa przecinające zakres pozycji Qt."""
        settings = self._asr_settings()
        if not settings.show_uncertain_words:
            return []
        threshold = settings.word_threshold
        return [
            item
            for item in self._items
            if item.anchor.is_uncertain(threshold)
            and item.cursor.selectionEnd() >= first
            and item.cursor.selectionStart() <= last
            and item.alive
            and not item.edited
        ]

    def update_uncertain(self) -> None:
        """Podkreśla niepewne słowa w widocznej części edytora (PERF-06)."""
        self._uncertain_timer.stop()
        if not any(item.anchor.source == WORD for item in self._items):
            self._editor.set_highlight_layer(UNCERTAIN_LAYER, [])
            return
        positions = self._editor.position_map()
        first, last = self._editor.visible_range(positions)
        color = QColor(tokens().danger)
        self._editor.set_highlight_layer(
            UNCERTAIN_LAYER,
            [
                dotted_underline(QTextCursor(item.cursor), color)
                for item in self._uncertain_items(
                    positions.to_qt(first), positions.to_qt(last)
                )
            ],
        )

    def uncertain_words(self) -> list[str]:
        """Tekst wszystkich podkreślanych słów (cały dokument; testy)."""
        return [
            item.cursor.selectedText()
            for item in self._uncertain_items(
                0, self._editor.document().characterCount()
            )
        ]

    def tooltip_at(self, position: int) -> str | None:
        positions = self._editor.position_map()
        qt_position = positions.to_qt(position)
        for item in self._uncertain_items(qt_position, qt_position):
            if item.cursor.selectionStart() <= qt_position < item.cursor.selectionEnd():
                probability = item.anchor.probability or 0.0
                return tr("sync.uncertain.tooltip", percent=round(probability * 100))
        return None

    # --- odtwarzanie z tekstu ----------------------------------------------

    def _current(self) -> list[Anchor]:
        """Kotwice z bieżącymi zakresami (bez porównywania tekstu słów)."""
        positions = self._editor.position_map()
        current: list[Anchor] = []
        for item in self._items:
            if not item.alive:
                continue
            start, end = self._editor.selection_range(item.cursor, positions)
            current.append(replace(item.anchor, start=start, end=end))
        return current

    def play_from_cursor(self) -> None:
        """Skrót „odtwórz od kursora”: segment lub znacznik przy kursorze."""
        cursor = self._editor.textCursor()
        position = self._editor.position_map().to_py(cursor.selectionStart())
        self.play_at(position, word_level=False)

    def play_at(self, position: int, word_level: bool = True) -> bool:
        """Odtwarza nagranie od kotwicy dla pozycji tekstu; False — brak kotwicy."""
        if self._player.source_path is None or not self._bar.has_media:
            self._show_status(tr("sync.no_media"))
            return False
        anchor = anchor_at(self._current(), position, word_level)
        if anchor is None:
            self._show_status(tr("sync.no_anchor"))
            return False
        if anchor.source == WORD:
            self._player.play_loop_once(
                anchor.start_ms - WORD_MARGIN_MS, anchor.end_ms + WORD_MARGIN_MS
            )
            return True
        start_ms = anchor.start_ms
        if anchor.source == SEGMENT:
            start_ms -= self._settings().segment_preroll_ms
        self._player.set_position(max(0, start_ms))
        self._player.play()
        return True

    # --- ręczne znaczniki --------------------------------------------------

    def insert_timestamp(self) -> bool:
        """Wstawia znacznik bieżącej pozycji nagrania w miejscu kursora."""
        if self._player.source_path is None or not self._bar.has_media:
            self._show_status(tr("sync.no_media"))
            return False
        positions = self._editor.position_map()
        position = positions.to_py(self._editor.textCursor().selectionStart())
        time_ms = self._player.position_ms
        self._remove_manual_at(position, positions)
        anchor = Anchor(position, position, time_ms, time_ms, MANUAL)
        self._items.append(self._track(anchor, positions))
        self._rebuild()
        self.anchors_changed.emit()
        self.timestamps_edited.emit()
        self._show_status(tr("sync.timestamp.inserted", time=format_ms(time_ms)))
        return True

    def manual_near(self, position: int) -> TrackedAnchor | None:
        """Znacznik ręczny w pozycji albo tuż obok (menu kontekstowe)."""
        positions = self._editor.position_map()
        for item in self._items:
            if item.anchor.source != MANUAL:
                continue
            start, _end = self._editor.selection_range(item.cursor, positions)
            if abs(start - position) <= 1:
                return item
        return None

    def remove(self, item: TrackedAnchor) -> None:
        if item in self._items:
            self._items.remove(item)
            self._rebuild()
            self.anchors_changed.emit()
            self.timestamps_edited.emit()

    def _remove_manual_at(self, position: int, positions: PositionMap) -> None:
        self._items = [
            item
            for item in self._items
            if item.anchor.source != MANUAL
            or self._editor.selection_range(item.cursor, positions)[0] != position
        ]

    def extend_context_menu(self, menu: QMenu, position: int) -> None:
        item = self.manual_near(position)
        if item is None:
            return
        menu.addSeparator()
        action = menu.addAction(
            tr("sync.timestamp.remove", time=format_ms(item.anchor.start_ms))
        )
        action.triggered.connect(
            lambda _checked=False, target=item: self.remove(target)
        )

    # --- podświetlenie aktywnego segmentu -----------------------------------

    def _on_position_changed(self, position_ms: int) -> None:
        self._last_position_ms = position_ms
        if not self._throttle.isActive():
            self._update_active()
            self._throttle.start()

    def _update_active(self) -> None:
        index = self._index.active_at(self._last_position_ms)
        if index is not None and not self._items[index].alive:
            index = None
        if index == self._active:
            return
        self._active = index
        if index is None:
            self._editor.set_highlight_layer(ACTIVE_LAYER, [])
            return
        cursor = QTextCursor(self._items[index].cursor)
        color = QColor(tokens().accent)
        color.setAlpha(ACTIVE_ALPHA)
        self._editor.set_highlight_layer(ACTIVE_LAYER, [background(cursor, color)])
        if self._settings().follow_playback and self._player.is_playing:
            self._editor.scroll_to_cursor(cursor)

    @property
    def active_anchor(self) -> Anchor | None:
        """Aktywny segment (do testów i fali)."""
        return None if self._active is None else self._items[self._active].anchor
