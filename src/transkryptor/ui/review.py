"""Wstawienie szkicu ASR i przegląd zmian reguł fonetycznych (REQ-14–REQ-16).

``ReviewController`` wstawia szkic do edytora, stosuje reguły wybrane przez
autora, śledzi każde dopasowanie kursorem edytora i synchronizuje listę
przeglądu w panelu ASR. Reguły pozostają w ``notation``; kontroler tylko je
uruchamia i prezentuje.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox, QWidget

from transkryptor.document.project import ReviewEntry
from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import EllipsisStyle, normalize_ellipses
from transkryptor.notation.suggestions import Suggestion, propose, without_overlaps
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.editor import TranscriptionEditor

DRAFT_REPLACE = "replace"
DRAFT_APPEND = "append"


@dataclass
class ReviewItem:
    """Dopasowanie reguły w szkicu ASR wraz ze śledzonym fragmentem edytora.

    Kursor obejmuje fragment oryginalny (propozycja) albo wstawioną zamianę
    (zmiana zastosowana) i przesuwa się razem z edycją tekstu.
    """

    suggestion: Suggestion
    cursor: QTextCursor
    applied: bool


class ReviewController(QObject):
    """Szkic ASR w edytorze i lista przeglądu automatycznych zmian."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        asr_panel: AsrPanel,
        dialog_parent: QWidget,
        ask_placement: Callable[[], str | None],
        ellipsis_style: Callable[[], EllipsisStyle],
    ) -> None:
        super().__init__(dialog_parent)
        self.editor = editor
        self.asr_panel = asr_panel
        self._dialog_parent = dialog_parent
        self._ask_placement = ask_placement
        self._ellipsis_style = ellipsis_style
        self.items: list[ReviewItem] = []

    def insert_draft(self, text: str) -> None:
        """REQ-14/15: wstawia szkic ASR i stosuje reguły wybrane przez autora.

        Wstawienie i reguły to dwa osobne kroki cofania: pierwsze Ctrl+Z
        przywraca surowy szkic, drugie — stan sprzed wstawienia (ACC-15).
        """
        if not text.strip():
            return
        if self.editor.plain_text().strip():
            placement = self._ask_placement()
            if placement is None:
                return
        else:
            placement = DRAFT_REPLACE
        self.finish()
        # Szkic nie wprowadza zapisu wielokropka innego niż wybrany.
        text = normalize_ellipses(text, self._ellipsis_style())
        start = self.editor.insert_draft(text, append=placement == DRAFT_APPEND)

        selected_codes = self.asr_panel.selected_rule_codes()
        positions = self.editor.position_map()
        self.items = [
            ReviewItem(
                suggestion,
                self.editor.track_range(
                    start + suggestion.start, start + suggestion.end, positions
                ),
                applied=suggestion.code in selected_codes,
            )
            for suggestion in without_overlaps(propose(text))
        ]
        self.editor.apply_tracked_replacements(
            [
                (
                    item.cursor,
                    item.suggestion.replacement,
                    item.suggestion.superscript_ranges,
                )
                for item in self.items
                if item.applied
            ]
        )
        self.refresh()
        self.editor.setFocus()

    def activate(self, index: int) -> None:
        """REQ-16: zaznacza w edytorze fragment pozycji z listy przeglądu."""
        cursor = self.items[index].cursor
        if not cursor.hasSelection():
            QMessageBox.information(
                self._dialog_parent,
                tr("review.title"),
                tr("review.gone"),
            )
            return
        self.editor.setTextCursor(QTextCursor(cursor))
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def apply(self, index: int) -> None:
        """ACC-12: stosuje propozycję tylko do jej fragmentu (jeden krok cofania).

        Gdy fragment zmienił się od transkrypcji, propozycja nie jest
        stosowana — dokument nie zmienia się bez wiedzy użytkownika (REQ-12).
        """
        item = self.items[index]
        if item.applied:
            return
        suggestion = item.suggestion
        if item.cursor.selectedText() != suggestion.original:
            QMessageBox.information(
                self._dialog_parent,
                tr("review.apply.title"),
                tr("review.apply.stale", fragment=suggestion.original),
            )
            return
        self.editor.apply_tracked_replacements(
            [(item.cursor, suggestion.replacement, suggestion.superscript_ranges)]
        )
        item.applied = True
        self.refresh()
        self.editor.setFocus()

    def refresh(self) -> None:
        self.editor.set_review_highlights(
            [item.cursor for item in self.items if item.applied]
        )
        self.asr_panel.set_review_items(
            [(item.suggestion, item.applied) for item in self.items]
        )

    def entries(self) -> list[ReviewEntry]:
        """Stan przeglądu do zapisu w projekcie (bieżące zakresy w tekście)."""
        positions = self.editor.position_map()
        return [
            _entry(item, *self.editor.selection_range(item.cursor, positions))
            for item in self.items
        ]

    def restore(self, entries: list[ReviewEntry] | tuple[ReviewEntry, ...]) -> None:
        """Odtwarza nieukończony przegląd z projektu (podświetlenia i listę)."""
        self.finish()
        if not entries:
            return
        positions = self.editor.position_map()
        self.items = [
            ReviewItem(
                Suggestion(
                    code=entry.code,
                    start=entry.suggestion_start,
                    end=entry.suggestion_end,
                    original=entry.original,
                    replacement=entry.replacement,
                    superscript_ranges=entry.superscript_ranges,
                    source=entry.source,
                    confidence=entry.confidence,
                    message=entry.message,
                    word=entry.word,
                    word_start=entry.word_start,
                ),
                self.editor.track_range(entry.start, entry.end, positions),
                applied=entry.applied,
            )
            for entry in entries
        ]
        self.refresh()

    def finish(self) -> None:
        """Usuwa podświetlenia i listę przeglądu; tekst się nie zmienia."""
        self.items = []
        self.editor.clear_review_highlights()
        self.asr_panel.clear_review()


def _entry(item: ReviewItem, start: int, end: int) -> ReviewEntry:
    """Wpis przeglądu z bieżącym zakresem fragmentu (pozycje Pythona)."""
    return ReviewEntry(
        start=start,
        end=end,
        applied=item.applied,
        code=item.suggestion.code,
        suggestion_start=item.suggestion.start,
        suggestion_end=item.suggestion.end,
        original=item.suggestion.original,
        replacement=item.suggestion.replacement,
        superscript_ranges=item.suggestion.superscript_ranges,
        source=item.suggestion.source,
        confidence=item.suggestion.confidence,
        message=item.suggestion.message,
        word=item.suggestion.word,
        word_start=item.suggestion.word_start,
    )


def ask_draft_placement(parent: QWidget) -> str | None:
    """Pyta, czy szkic zastępuje tekst edytora, czy jest dopisywany."""
    box, replace_button, append_button = draft_placement_box(parent)
    box.exec()
    clicked = box.clickedButton()
    if clicked is replace_button:
        return DRAFT_REPLACE
    if clicked is append_button:
        return DRAFT_APPEND
    return None


def draft_placement_box(parent: QWidget) -> tuple[QMessageBox, object, object]:
    """Dialog wyboru miejsca szkicu: (okno, „Zastąp całość”, „Dopisz”)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(tr("review.placement.title"))
    box.setText(tr("review.placement.text"))
    replace_button = box.addButton(
        tr("review.placement.replace"), QMessageBox.ButtonRole.DestructiveRole
    )
    append_button = box.addButton(
        tr("review.placement.append"), QMessageBox.ButtonRole.AcceptRole
    )
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(append_button)
    return box, replace_button, append_button
