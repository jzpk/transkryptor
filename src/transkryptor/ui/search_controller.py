"""Logika paska wyszukiwania: trafienia, podświetlenia i zamiana (propozycja 20).

Wyszukiwanie i parsowanie zamiennika to czyste funkcje z
``document/search.py``; kontroler łączy je z edytorem. Podświetlenia są
warstwą ``ExtraSelections`` (widok), więc nie trafiają do dokumentu ani do
DOCX. Zamiana idzie przez ``apply_tracked_replacements`` — „zamień wszystkie”
to jeden krok cofania (NFR-04).
"""

from __future__ import annotations

import re

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QTextCursor
from PySide6.QtWidgets import QWidget

from transkryptor.document.search import (
    ParsedReplacement,
    SearchError,
    compile_query,
    find_all,
    parse_replacement,
)
from transkryptor.i18n import tr
from transkryptor.ui.editor import SEARCH_LAYER, TranscriptionEditor, highlight
from transkryptor.ui.search_bar import SearchBar
from transkryptor.ui.shortcuts import (
    FIND_NEXT_SHORTCUT,
    FIND_PREVIOUS_SHORTCUT,
    FIND_SHORTCUT,
    REPLACE_SHORTCUT,
)
from transkryptor.ui.theme import tokens

SEARCH_DEBOUNCE_MS = 150
MATCH_ALPHA = 70
CURRENT_MATCH_ALPHA = 170


class SearchController(QObject):
    """Steruje paskiem ``SearchBar`` dla edytora transkrypcji."""

    def __init__(
        self, editor: TranscriptionEditor, bar: SearchBar, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.bar = bar
        self._matches: list[tuple[int, int]] = []
        self._current: int | None = None
        self._query_error: str | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)

        editor.document().contentsChanged.connect(self._on_text_changed)
        bar.query_changed.connect(self._on_query_changed)
        bar.replacement_changed.connect(self._update_preview)
        bar.next_requested.connect(self.find_next)
        bar.previous_requested.connect(self.find_previous)
        bar.replace_requested.connect(self.replace_current)
        bar.replace_all_requested.connect(self.replace_all)
        bar.close_requested.connect(self.close)

    def create_actions(self, owner: QWidget) -> dict[str, QAction]:
        """Ctrl+F / Ctrl+H / F3 / Shift+F3 z fokusem w edytorze (poza paskiem)."""
        definitions = (
            ("find", tr("search.action.find"), FIND_SHORTCUT, self.open_find),
            (
                "replace",
                tr("search.action.replace"),
                REPLACE_SHORTCUT,
                self.open_replace,
            ),
            (
                "find_next",
                tr("search.action.next"),
                FIND_NEXT_SHORTCUT,
                self.find_next,
            ),
            (
                "find_previous",
                tr("search.action.previous"),
                FIND_PREVIOUS_SHORTCUT,
                self.find_previous,
            ),
        )
        actions: dict[str, QAction] = {}
        for key, label, shortcut, handler in definitions:
            action = QAction(label, owner)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(lambda _checked=False, run=handler: run())
            owner.addAction(action)
            actions[key] = action
        return actions

    # --- otwieranie i zamykanie --------------------------------------------

    @property
    def matches(self) -> list[tuple[int, int]]:
        return list(self._matches)

    @property
    def current_index(self) -> int | None:
        return self._current

    def is_open(self) -> bool:
        # ``isHidden`` nie zależy od widoczności okna (testy offscreen).
        return not self.bar.isHidden()

    def open_find(self) -> None:
        self._open(replace=False)

    def open_replace(self) -> None:
        self._open(replace=True)

    def _open(self, replace: bool) -> None:
        selected = self.editor.textCursor().selectedText()
        # Zaznaczenie w jednym wierszu wypełnia pole „Szukaj” (U+2029 = akapit).
        if selected and " " not in selected:
            self.bar.find_edit.setText(selected)
        self.bar.set_replace_mode(replace)
        self.bar.show()
        if replace and self.bar.find_edit.text():
            self.bar.replace_edit.setFocus()
            self.bar.replace_edit.selectAll()
        else:
            self.bar.find_edit.setFocus()
            self.bar.find_edit.selectAll()
        self.refresh()
        self._update_preview()

    def close(self) -> None:
        """Esc: chowa pasek, usuwa podświetlenia i oddaje fokus edytorowi."""
        self._timer.stop()
        self.bar.hide()
        self._matches = []
        self._current = None
        self.editor.set_highlight_layer(SEARCH_LAYER, [])
        self.editor.setFocus()

    # --- trafienia ----------------------------------------------------------

    def _on_text_changed(self) -> None:
        if self.is_open():
            self._timer.start()

    def _on_query_changed(self) -> None:
        self._current = None
        self.refresh()

    def _pattern(self) -> re.Pattern[str] | None:
        query = self.bar.find_edit.text()
        self._query_error = None
        if not query:
            return None
        try:
            return compile_query(query, self.bar.options())
        except SearchError as error:
            self._query_error = str(error)
            return None

    def refresh(self) -> None:
        """Przelicza trafienia i podświetlenia (ACC-27: błąd → komunikat)."""
        self._timer.stop()
        pattern = self._pattern()
        self._matches = (
            find_all(self.editor.toPlainText(), pattern) if pattern is not None else []
        )
        if self._current is not None and self._current >= len(self._matches):
            self._current = None
        self._show_state()

    def _show_state(self) -> None:
        self.bar.set_error(self._query_error or self._replacement_error())
        self.bar.set_count(self._current, len(self._matches))
        t = tokens()
        selections = []
        for index, (start, end) in enumerate(self._matches):
            color = QColor(t.accent)
            color.setAlpha(
                CURRENT_MATCH_ALPHA if index == self._current else MATCH_ALPHA
            )
            selections.append(highlight(self.editor.track_range(start, end), color))
        self.editor.set_highlight_layer(SEARCH_LAYER, selections)

    def find_next(self) -> None:
        self._step(forward=True)

    def find_previous(self) -> None:
        self._step(forward=False)

    def _step(self, forward: bool) -> None:
        if not self.is_open():
            self.open_find()
        self.refresh()
        if not self._matches:
            return
        cursor = self.editor.textCursor()
        if forward:
            position = (
                cursor.selectionEnd() if cursor.hasSelection() else cursor.position()
            )
            following = [i for i, (s, _e) in enumerate(self._matches) if s >= position]
            self._current = following[0] if following else 0
        else:
            position = cursor.selectionStart()
            preceding = [i for i, (_s, e) in enumerate(self._matches) if e <= position]
            self._current = preceding[-1] if preceding else len(self._matches) - 1
        self._select_current()

    def _select_current(self) -> None:
        if self._current is None:
            return
        start, end = self._matches[self._current]
        self.editor.setTextCursor(self.editor.track_range(start, end))
        self.editor.ensureCursorVisible()
        self._show_state()

    # --- zamiana ------------------------------------------------------------

    def _replacement(self) -> ParsedReplacement | None:
        try:
            return parse_replacement(self.bar.replace_edit.text())
        except SearchError:
            return None

    def _replacement_error(self) -> str | None:
        if not self.bar.is_replace_mode():
            return None
        try:
            parse_replacement(self.bar.replace_edit.text())
        except SearchError as error:
            return str(error)
        return None

    def _update_preview(self) -> None:
        self.bar.set_preview(self._replacement())
        self.bar.set_error(self._query_error or self._replacement_error())

    def replace_current(self) -> None:
        """Zamienia bieżące trafienie i przechodzi do następnego."""
        replacement = self._replacement()
        self.refresh()
        if replacement is None or not self._matches:
            return
        if self._current is None:
            self.find_next()
            return
        start, end = self._matches[self._current]
        cursor = self.editor.track_range(start, end)
        self.editor.apply_tracked_replacements(
            [(cursor, replacement.text, replacement.superscript_ranges)]
        )
        after = QTextCursor(self.editor.document())
        after.setPosition(cursor.selectionEnd())
        self.editor.setTextCursor(after)
        self._current = None
        self.refresh()
        if self._matches:
            self.find_next()

    def replace_all(self) -> int:
        """ACC-26: zamienia wszystkie trafienia jednym krokiem cofania."""
        replacement = self._replacement()
        self.refresh()
        if replacement is None or not self._matches:
            return 0
        cursors = [self.editor.track_range(s, e) for s, e in self._matches]
        self.editor.apply_tracked_replacements(
            [
                (cursor, replacement.text, replacement.superscript_ranges)
                for cursor in cursors
            ]
        )
        count = len(cursors)
        self._current = None
        self.refresh()
        self.bar.count_label.setText(tr("search.replaced", count=count))
        return count
