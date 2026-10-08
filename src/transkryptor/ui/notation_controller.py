"""Notacja w edytorze: markery, ujednolicenie wielokropków i walidacja.

Reguły zapisu są w ``notation`` (czyste funkcje); kontroler wstawia markery
w stylu z ustawień, uruchamia walidator z debounce i prezentuje ostrzeżenia
w ``WarningsPanel`` z nawigacją do fragmentu tekstu.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import QLabel, QWidget

from transkryptor.document.model import Document
from transkryptor.notation.ellipsis import (
    EllipsisStyle,
    ellipsis_text,
    foreign_ellipses,
)
from transkryptor.notation.validator import validate
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.markers import marker_text
from transkryptor.ui.theme import set_props
from transkryptor.ui.warnings_panel import WarningsPanel

VALIDATION_DEBOUNCE_MS = 300


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
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.warnings_panel = warnings_panel
        self._count_label = count_label
        self._document = document
        self._style = ellipsis_style
        self._show_message = show_message
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(VALIDATION_DEBOUNCE_MS)
        self.timer.timeout.connect(self.run_validation)
        warnings_panel.warning_activated.connect(self.go_to_range)

    def create_unify_action(self, owner: QWidget) -> QAction:
        action = QAction("Ujednolić wielokropki", owner)
        action.setToolTip(
            "Zamień wszystkie wielokropki na zapis wybrany w ustawieniach "
            "(jeden krok cofania)"
        )
        action.triggered.connect(lambda _checked=False: self.unify_ellipses())
        owner.addAction(action)
        return action

    def insert_marker(self, key: str) -> None:
        self.editor.insert_marker(marker_text(key, self._style()))
        self.editor.setFocus()

    def unify_ellipses(self) -> int:
        """ACC-24: wszystkie wielokropki w stylu z ustawień, jeden krok cofania."""
        wanted = ellipsis_text(self._style())
        ranges = foreign_ellipses(self.editor.toPlainText(), self._style())
        self.editor.apply_tracked_replacements(
            [(self.editor.track_range(start, end), wanted, ()) for start, end in ranges]
        )
        if ranges:
            self._show_message(f"Ujednolicono wielokropki: {len(ranges)} → „{wanted}”")
        else:
            self._show_message(f"Wszystkie wielokropki mają już zapis „{wanted}”")
        self.run_validation()
        return len(ranges)

    def schedule_validation(self) -> None:
        self.timer.start()

    def run_validation(self) -> None:
        self.timer.stop()
        self.warnings_panel.set_warnings(validate(self._document().text, self._style()))
        self.update_warning_count()

    def clear(self) -> None:
        self.warnings_panel.set_warnings([])
        self.update_warning_count()

    def update_warning_count(self) -> None:
        count = self.warnings_panel.warning_count()
        self._count_label.setText(str(count))
        tone = "warning" if self.warnings_panel.has_errors() else ""
        set_props(self._count_label, tone=tone if count else "success")

    def go_to_range(self, start: int, end: int) -> None:
        cursor = self.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.editor.setFocus()
