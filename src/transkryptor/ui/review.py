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
        if self.editor.toPlainText().strip():
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
        self.items = [
            ReviewItem(
                suggestion,
                self.editor.track_range(
                    start + suggestion.start, start + suggestion.end
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
                "Przegląd zmian",
                "Tego fragmentu nie ma już w tekście — został usunięty "
                "albo cofnięty.",
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
                "Zastosowanie propozycji",
                f"Fragment „{suggestion.original}” zmienił się od transkrypcji, "
                "więc propozycja nie jest już aktualna. Popraw go ręcznie.",
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

    def finish(self) -> None:
        """Usuwa podświetlenia i listę przeglądu; tekst się nie zmienia."""
        self.items = []
        self.editor.clear_review_highlights()
        self.asr_panel.clear_review()


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
    box.setWindowTitle("Wstawienie szkicu ASR")
    box.setText(
        "Edytor zawiera już tekst. Co zrobić ze szkicem ASR?\n\n"
        "Obie operacje można cofnąć (Ctrl+Z). Po anulowaniu szkic można "
        "wstawić później przyciskiem „Wstaw szkic ponownie”."
    )
    replace_button = box.addButton(
        "Zastąp całość", QMessageBox.ButtonRole.DestructiveRole
    )
    append_button = box.addButton("Dopisz na końcu", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(append_button)
    return box, replace_button, append_button
