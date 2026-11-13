"""Warstwa podświetleń tłem dla zakresów tekstu, rysowana tylko w widoku.

Kontroler podaje zakresy (pozycje Pythona) z kolorami, a warstwa zamienia
na ``ExtraSelections`` tylko te w widocznej części edytora (PERF-06).
Przewinięcie i zmiana rozmiaru odświeżają podświetlenia bez ponownego
liczenia zakresów. Zakresy mogą na siebie nachodzić.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor

from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import background

# Bezpiecznik na bardzo gęste zakresy w jednym ekranie.
MAX_VISIBLE_SPANS = 2000


class SpanLayer(QObject):
    """Zakresy ``(start, end, kolor)`` jednej warstwy podświetleń edytora."""

    def __init__(
        self, editor: TranscriptionEditor, layer: str, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._layer = layer
        self._spans: list[tuple[int, int, QColor]] = []
        self._starts: list[int] = []
        self._longest = 0
        editor.verticalScrollBar().valueChanged.connect(self._on_view_changed)
        editor.horizontalScrollBar().valueChanged.connect(self._on_view_changed)
        editor.viewport().installEventFilter(self)

    def set_spans(self, spans: Sequence[tuple[int, int, QColor]]) -> None:
        self._spans = sorted(spans, key=lambda span: span[0])
        self._starts = [span[0] for span in self._spans]
        self._longest = max((end - start for start, end, _ in self._spans), default=0)
        self.render()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # API Qt
        if event.type() == QEvent.Type.Resize:
            self._on_view_changed()
        return super().eventFilter(watched, event)

    def _on_view_changed(self) -> None:
        if self._spans:
            self.render()

    def render(self) -> None:
        editor = self._editor
        if not self._spans:
            editor.set_highlight_layer(self._layer, [])
            return
        positions = editor.position_map()
        first, last = editor.visible_range(positions)
        lo = bisect_left(self._starts, first - self._longest)
        hi = bisect_left(self._starts, last)
        selections = []
        for start, end, color in self._spans[lo:hi]:
            if end <= first:
                continue
            cursor = editor.track_range(start, end, positions)
            selections.append(background(cursor, color))
            if len(selections) >= MAX_VISIBLE_SPANS:
                break
        editor.set_highlight_layer(self._layer, selections)
