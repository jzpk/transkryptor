"""Notacja w edytorze: markery, ujednolicenie wielokropków i walidacja.

Reguły zapisu są w ``notation`` (czyste funkcje); kontroler wstawia markery
w stylu z ustawień, uruchamia walidator z debounce i prezentuje ostrzeżenia
w ``WarningsPanel`` z nawigacją do fragmentu tekstu oraz jako faliste
podkreślenia w edytorze (warstwa ``WARNINGS_LAYER``) z opisem po najechaniu.
„Ignoruj tutaj” zapamiętuje kod reguły i śledzony zakres tekstu
(``IgnoredWarnings``) - zapisywane w pliku projektu, nie w tekście.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction, QColor, QTextCursor
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from transkryptor.document.model import Document
from transkryptor.document.project import IgnoredWarning
from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import (
    EllipsisStyle,
    ellipsis_text,
    foreign_ellipses,
)
from transkryptor.notation.validator import SEVERITY_HINT, NotationWarning, validate
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import WARNINGS_LAYER, wave_underline
from transkryptor.ui.markers import marker_text
from transkryptor.ui.positions import PositionMap
from transkryptor.ui.theme import set_props, tokens
from transkryptor.ui.warnings_panel import WarningsPanel

VALIDATION_DEBOUNCE_MS = 300


class IgnoredWarnings:
    """Ostrzeżenia zignorowane w konkretnych miejscach tekstu.

    Każde zignorowanie to kod reguły i kursor edytora przesuwający się razem
    z edycją. Ostrzeżenie jest pomijane, gdy ma ten sam kod i dokładnie ten
    sam zakres; usunięty fragment (pusty kursor) przestaje być ignorowany.
    """

    def __init__(self, editor: TranscriptionEditor) -> None:
        self._editor = editor
        self._items: list[tuple[str, QTextCursor]] = []

    def add(self, warning: NotationWarning) -> None:
        self._items.append(
            (warning.code, self._editor.track_range(warning.start, warning.end))
        )

    def clear(self) -> None:
        self._items = []

    def filter(
        self, warnings: list[NotationWarning], positions: PositionMap | None = None
    ) -> list[NotationWarning]:
        """Ostrzeżenia bez zignorowanych; porządkuje zniknięte fragmenty."""
        if not self._items:
            return warnings
        if positions is None:
            positions = self._editor.position_map()
        self._items = [item for item in self._items if item[1].hasSelection()]
        ignored = {
            (code, *self._editor.selection_range(cursor, positions))
            for code, cursor in self._items
        }
        return [w for w in warnings if (w.code, w.start, w.end) not in ignored]

    def entries(self) -> list[IgnoredWarning]:
        """Stan do zapisu w projekcie (bieżące zakresy w tekście)."""
        positions = self._editor.position_map()
        text = positions.text
        entries: list[IgnoredWarning] = []
        for code, cursor in self._items:
            if not cursor.hasSelection():
                continue
            start, end = self._editor.selection_range(cursor, positions)
            entries.append(IgnoredWarning(code, start, end, text[start:end]))
        return entries

    def restore(self, entries: Iterable[IgnoredWarning]) -> None:
        """Odtwarza zignorowania z projektu; pomija fragmenty, które się zmieniły."""
        self.clear()
        positions = self._editor.position_map()
        text = positions.text
        for entry in entries:
            if entry.end > len(text) or text[entry.start : entry.end] != entry.text:
                continue
            self._items.append(
                (
                    entry.code,
                    self._editor.track_range(entry.start, entry.end, positions),
                )
            )


class NotationController(QObject):
    """Markery, „Ujednolić wielokropki” i nieblokująca walidacja (REQ-05/06)."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        warnings_panel: WarningsPanel,
        count_label: QLabel,
        document: Callable[[], Document],
        ellipsis_style: Callable[[], EllipsisStyle],
        show_message: Callable[[str], None],
        parent: QObject | None = None,
        enabled_rules: Callable[[], frozenset[str] | None] = lambda: None,
        ignored: IgnoredWarnings | None = None,
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.warnings_panel = warnings_panel
        self._count_label = count_label
        self._document = document
        self._style = ellipsis_style
        self._show_message = show_message
        self._enabled_rules = enabled_rules
        self.ignored = ignored if ignored is not None else IgnoredWarnings(editor)
        # Ostrzeżenia z kursorami podkreśleń (podpowiedź i „Ignoruj tutaj”).
        self._warnings: list[tuple[NotationWarning, QTextCursor]] = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(VALIDATION_DEBOUNCE_MS)
        self.timer.timeout.connect(self.run_validation)
        warnings_panel.warning_activated.connect(self.go_to_range)
        warnings_panel.ignore_requested.connect(self.ignore_warning)
        editor.tooltip_providers.append(self.tooltip_at)
        editor.context_menu_extenders.append(self.extend_context_menu)

    def create_unify_action(self, owner: QWidget) -> QAction:
        action = QAction(tr("notation.unify"), owner)
        action.setToolTip(tr("notation.unify.tooltip"))
        action.triggered.connect(lambda _checked=False: self.unify_ellipses())
        owner.addAction(action)
        return action

    def insert_marker(self, key: str) -> None:
        self.editor.insert_marker(marker_text(key, self._style()))
        self.editor.setFocus()

    def unify_ellipses(self) -> int:
        """ACC-24: wszystkie wielokropki w stylu z ustawień, jeden krok cofania."""
        wanted = ellipsis_text(self._style())
        text = self.editor.plain_text()
        ranges = foreign_ellipses(text, self._style())
        positions = PositionMap(text)
        self.editor.apply_tracked_replacements(
            [
                (self.editor.track_range(start, end, positions), wanted, ())
                for start, end in ranges
            ]
        )
        if ranges:
            self._show_message(
                tr("notation.unify.done", count=len(ranges), wanted=wanted)
            )
        else:
            self._show_message(tr("notation.unify.nothing", wanted=wanted))
        self.run_validation()
        return len(ranges)

    def schedule_validation(self) -> None:
        self.timer.start()

    def run_validation(self) -> None:
        self.timer.stop()
        document = self._document()
        warnings = validate(
            document.text,
            self._style(),
            document.superscript_ranges,
            self._enabled_rules(),
            document.paragraph_speakers,
        )
        positions = self.editor.position_map()
        if positions.text != document.text:
            # Dokument zawsze odczytuje edytor; ostrożnie, gdyby się rozjechały.
            positions = PositionMap(document.text)
        warnings = self.ignored.filter(warnings, positions)
        self.warnings_panel.set_warnings(warnings)
        self._show_underlines(warnings, positions)
        self.update_warning_count()

    def clear(self) -> None:
        self.ignored.clear()
        self._warnings = []
        self.editor.set_highlight_layer(WARNINGS_LAYER, [])
        self.warnings_panel.set_warnings([])
        self.update_warning_count()

    @property
    def warnings(self) -> list[NotationWarning]:
        """Bieżące (niezignorowane) ostrzeżenia."""
        return [warning for warning, _cursor in self._warnings]

    def update_warning_count(self) -> None:
        count = self.warnings_panel.warning_count()
        self._count_label.setText(str(count))
        tone = "warning" if self.warnings_panel.has_errors() else ""
        set_props(self._count_label, tone=tone if count else "success")

    def go_to_range(self, start: int, end: int) -> None:
        """Zaznacza fragment ostrzeżenia (pozycje walidatora to punkty kodowe)."""
        self.editor.setTextCursor(self.editor.track_range(start, end))
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    # --- ostrzeżenia w tekście ------------------------------------------------

    def ignore_warning(self, warning: NotationWarning) -> None:
        """„Ignoruj tutaj”: to jedno wystąpienie przestaje być zgłaszane."""
        self.ignored.add(warning)
        self.run_validation()
        self._show_message(tr("warnings.ignored", code=warning.code))

    def warnings_at(self, position: int) -> list[NotationWarning]:
        """Ostrzeżenia, których zakres obejmuje pozycję (punkty kodowe)."""
        return [w for w in self.warnings if w.start <= position <= w.end]

    def tooltip_at(self, position: int) -> str | None:
        found = self.warnings_at(position)
        if not found:
            return None
        return "\n".join(f"{w.code} - {w.message}" for w in found)

    def extend_context_menu(self, menu: QMenu, position: int) -> None:
        """Dopisuje „Ignoruj tutaj” dla ostrzeżeń pod kursorem myszy."""
        found = self.warnings_at(position)
        if not found:
            return
        menu.addSeparator()
        for warning in found:
            action = menu.addAction(tr("warnings.ignore_here", code=warning.code))
            action.triggered.connect(
                lambda _checked=False, chosen=warning: self.ignore_warning(chosen)
            )

    def _show_underlines(
        self, warnings: list[NotationWarning], positions: PositionMap
    ) -> None:
        t = tokens()
        warning_color = QColor(t.warning)
        hint_color = QColor(t.text_muted)
        self._warnings = []
        selections = []
        for warning in warnings:
            cursor = self.editor.track_range(warning.start, warning.end, positions)
            self._warnings.append((warning, cursor))
            color = hint_color if warning.severity == SEVERITY_HINT else warning_color
            selections.append(wave_underline(cursor, color))
        self.editor.set_highlight_layer(WARNINGS_LAYER, selections)
