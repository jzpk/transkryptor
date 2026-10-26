"""Komentarze recenzji w edytorze (faza 14, REQ-27, ACC-64).

``CommentsController`` śledzi fragment każdego komentarza kursorem edytora,
który przesuwa się razem z edycją - jak kotwice czasowe i pozycje przeglądu
reguł. Komentarz, którego fragment usunięto, zostaje (punkt w miejscu
fragmentu, z cytatem z chwili zapisu). Kontroler obsługuje:

- dodanie komentarza do zaznaczenia (przycisk panelu, menu kontekstowe,
  konfigurowalny skrót), odpowiedzi (wątek jednopoziomowy), edycję i usunięcie;
- tło komentowanych fragmentów (warstwa ``COMMENT_LAYER``) i podpowiedź
  z treścią po najechaniu;
- przejście do fragmentu (także skrótami „następny/poprzedni komentarz”)
  i odsłuch od jego kotwicy czasowej;
- rozwiązanie komentarza i ponowne otwarcie. Rozwiązany komentarz zostaje
  w projekcie i w panelu, ale jego fragment nie ma tła, a skróty
  „następny/poprzedni komentarz” go pomijają - prowadzą po otwartych.

Komentarze należą do projektu (``ProjectState.comments``), nie do tekstu.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QColor, QTextCursor
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from transkryptor.document.comments import (
    Comment,
    Reply,
    display_date,
    new_comment,
    now,
)
from transkryptor.i18n import tr
from transkryptor.ui.comment_dialog import ask_comment
from transkryptor.ui.comments_panel import CommentsPanel
from transkryptor.ui.compare_panel import short
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import COMMENT_LAYER, background
from transkryptor.ui.navigation import step
from transkryptor.ui.positions import PositionMap
from transkryptor.ui.sync_controller import SyncController
from transkryptor.ui.theme import tokens

COMMENT_ALPHA = 55


@dataclass
class CommentItem:
    """Komentarz i kursor obejmujący jego fragment w edytorze."""

    comment: Comment
    cursor: QTextCursor


class CommentsController(QObject):
    """Komentarze z wątkami: edytor, panel i stan projektu."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        sync: SyncController,
        author: Callable[[], str],
        remember_author: Callable[[str], None],
        on_changed: Callable[[], None],
        dialog_parent: QWidget,
        show_status: Callable[[str], None] = lambda _text: None,
    ) -> None:
        super().__init__(dialog_parent)
        self.editor = editor
        self._sync = sync
        self._author = author
        self._remember_author = remember_author
        self._on_changed = on_changed
        self._parent = dialog_parent
        self._show_status = show_status
        # Okno autora i treści; testy podstawiają atrapę.
        self.ask = ask_comment
        self.items: list[CommentItem] = []
        self.panel = CommentsPanel()
        self.panel.add_requested.connect(self.add_from_selection)
        self.panel.activated.connect(self.activate)
        self.panel.reply_requested.connect(self.reply)
        self.panel.edit_requested.connect(self.edit)
        self.panel.remove_requested.connect(self.remove)
        self.panel.play_requested.connect(self.play)
        self.panel.resolve_requested.connect(self.toggle_resolved)
        self.add_action = QAction(tr("comments.action.add"), dialog_parent)
        self.add_action.triggered.connect(
            lambda _checked=False: self.add_from_selection()
        )
        dialog_parent.addAction(self.add_action)
        editor.tooltip_providers.append(self.tooltip_at)
        editor.context_menu_extenders.append(self.extend_context_menu)

    # --- dodawanie i wątki ------------------------------------------------

    def _ask(
        self, title: str, text: str = "", context: str = ""
    ) -> tuple[str, str] | None:
        answer = self.ask(self._parent, title, self._author(), text, context)
        if answer is None or not answer[1]:
            return None
        if answer[0] != self._author():
            self._remember_author(answer[0])
        return answer

    def add_from_selection(self) -> bool:
        """Komentarz do zaznaczonego fragmentu; False - brak zaznaczenia albo rezygnacja."""
        selection = self.editor.textCursor()
        if not selection.hasSelection():
            QMessageBox.information(
                self._parent, tr("comments.title"), tr("comments.no_selection")
            )
            return False
        positions = self.editor.position_map()
        start, end = self.editor.selection_range(selection, positions)
        quote = positions.text[start:end]
        answer = self._ask(
            tr("comments.add.title"), context=tr("comments.quote", quote=short(quote))
        )
        if answer is None:
            return False
        author, text = answer
        comment = new_comment(start, end, quote, author, text)
        self.items.append(CommentItem(comment, self._track(start, end, positions)))
        self.items.sort(key=lambda item: item.cursor.selectionStart())
        self._changed()
        self.panel.select(self._index_of(comment.id))
        return True

    def reply(self, index: int) -> bool:
        item = self.items[index]
        answer = self._ask(
            tr("comments.reply.title"),
            context=tr(
                "comments.reply.context",
                author=item.comment.author or tr("comments.anonymous"),
                text=item.comment.text,
            ),
        )
        if answer is None:
            return False
        author, text = answer
        item.comment = item.comment.with_reply(Reply(author, now(), text))
        self._changed()
        self.panel.select(index, len(item.comment.replies) - 1)
        return True

    def edit(self, index: int, reply: int | None = None) -> bool:
        """Zmienia treść komentarza albo odpowiedzi (autor i data zostają)."""
        item = self.items[index]
        current = (
            item.comment.text if reply is None else item.comment.replies[reply].text
        )
        answer = self.ask(
            self._parent, tr("comments.edit.title"), self._author(), current, ""
        )
        if answer is None or not answer[1] or answer[1] == current:
            return False
        text = answer[1]
        if reply is None:
            item.comment = replace(item.comment, text=text)
        else:
            replies = list(item.comment.replies)
            replies[reply] = replace(replies[reply], text=text)
            item.comment = replace(item.comment, replies=tuple(replies))
        self._changed()
        return True

    def remove(self, index: int, reply: int | None = None) -> bool:
        """Usuwa komentarz z wątkiem albo jedną odpowiedź (po potwierdzeniu)."""
        text = (
            tr("comments.remove.text")
            if reply is None
            else tr("comments.remove_reply.text")
        )
        answer = QMessageBox.question(
            self._parent,
            tr("comments.remove.title"),
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        item = self.items[index]
        if reply is None:
            self.items.remove(item)
        else:
            replies = list(item.comment.replies)
            del replies[reply]
            item.comment = replace(item.comment, replies=tuple(replies))
        self._changed()
        return True

    def toggle_resolved(self, index: int) -> bool:
        """Oznacza komentarz jako rozwiązany albo otwiera go ponownie."""
        if not 0 <= index < len(self.items):
            return False
        item = self.items[index]
        item.comment = replace(item.comment, resolved=not item.comment.resolved)
        self._changed()
        self.panel.select(index)
        self._show_status(
            tr(
                "comments.resolved.status"
                if item.comment.resolved
                else "comments.reopened.status"
            )
        )
        return True

    def open_count(self) -> int:
        return sum(1 for item in self.items if not item.comment.resolved)

    # --- przejście i odsłuch ---------------------------------------------

    def activate(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        self.editor.setTextCursor(QTextCursor(self.items[index].cursor))
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def go_to(self, direction: int) -> bool:
        """Przechodzi do następnego (1) albo poprzedniego (-1) otwartego komentarza.

        Zaznacza komentowany fragment i komentarz w panelu; w pasku stanu
        jest autor i początek treści. False - brak otwartych komentarzy.
        """
        order = sorted(
            (
                index
                for index, item in enumerate(self.items)
                if not item.comment.resolved
            ),
            key=lambda index: self.items[index].cursor.selectionStart(),
        )
        cursor = self.editor.textCursor()
        target = step(
            [
                (
                    self.items[index].cursor.selectionStart(),
                    self.items[index].cursor.selectionEnd(),
                )
                for index in order
            ],
            (cursor.selectionStart(), cursor.selectionEnd()),
            direction,
        )
        if target is None:
            self._show_status(
                tr("comments.none_open" if self.items else "comments.none")
            )
            return False
        position, wrapped = target
        index = order[position]
        self.activate(index)
        self.panel.select(index)
        comment = self.items[index].comment
        message = tr(
            "comments.position",
            index=position + 1,
            count=len(order),
            author=comment.author or tr("comments.anonymous"),
            text=short(comment.text),
        )
        if wrapped:
            message = f"{message} - {tr('sync.uncertain.wrapped')}"
        self._show_status(message)
        return True

    def play(self, index: int) -> None:
        start, _end = self.editor.selection_range(self.items[index].cursor)
        self._sync.play_at(start)

    # --- edytor -----------------------------------------------------------

    def comments_at(self, position: int) -> list[Comment]:
        positions = self.editor.position_map()
        found: list[Comment] = []
        for item in self.items:
            start, end = self.editor.selection_range(item.cursor, positions)
            if start <= position < end:
                found.append(item.comment)
        return found

    def tooltip_at(self, position: int) -> str | None:
        comments = self.comments_at(position)
        if not comments:
            return None
        lines: list[str] = []
        for comment in comments:
            line = tr(
                "comments.tooltip",
                author=comment.author or tr("comments.anonymous"),
                date=display_date(comment.created),
                text=comment.text,
            )
            if comment.resolved:
                line = tr("comments.tooltip.resolved", line=line)
            lines.append(line)
            lines.extend(
                tr(
                    "comments.tooltip.reply",
                    author=reply.author or tr("comments.anonymous"),
                    text=reply.text,
                )
                for reply in comment.replies
            )
        return "\n".join(lines)

    def extend_context_menu(self, menu: QMenu, position: int) -> None:
        commented = [
            index
            for index, item in enumerate(self.items)
            if item.comment in self.comments_at(position)
        ]
        if not self.editor.textCursor().hasSelection() and not commented:
            return
        menu.addSeparator()
        if self.editor.textCursor().hasSelection():
            menu.addAction(self.add_action)
        for index in commented:
            action = menu.addAction(
                tr(
                    "comments.action.reply",
                    author=self.items[index].comment.author or tr("comments.anonymous"),
                )
            )
            action.triggered.connect(
                lambda _checked=False, target=index: self.reply(target)
            )
            comment = self.items[index].comment
            toggle = menu.addAction(
                tr(
                    (
                        "comments.action.reopen"
                        if comment.resolved
                        else "comments.action.resolve"
                    ),
                    author=comment.author or tr("comments.anonymous"),
                )
            )
            toggle.triggered.connect(
                lambda _checked=False, target=index: self.toggle_resolved(target)
            )

    def refresh(self) -> None:
        color = QColor(tokens().warning)
        color.setAlpha(COMMENT_ALPHA)
        self.editor.set_highlight_layer(
            COMMENT_LAYER,
            [
                background(QTextCursor(item.cursor), color)
                for item in self.items
                if item.cursor.hasSelection() and not item.comment.resolved
            ],
        )
        self.panel.set_comments(self.entries())

    # --- stan projektu ----------------------------------------------------

    def entries(self, positions: PositionMap | None = None) -> list[Comment]:
        """Komentarze z bieżącymi zakresami (i cytatem, gdy fragment istnieje)."""
        if positions is None:
            positions = self.editor.position_map()
        result: list[Comment] = []
        for item in self.items:
            start, end = self.editor.selection_range(item.cursor, positions)
            quote = positions.text[start:end] if end > start else item.comment.quote
            result.append(replace(item.comment, start=start, end=end, quote=quote))
        return result

    def restore(self, comments: Iterable[Comment]) -> None:
        """Odtwarza komentarze z projektu (zakresy sprawdzone przy odczycie)."""
        positions = self.editor.position_map()
        length = len(positions.text)
        self.items = [
            CommentItem(
                comment,
                self._track(
                    min(comment.start, length), min(comment.end, length), positions
                ),
            )
            for comment in comments
        ]
        self.refresh()

    def clear(self) -> None:
        self.items = []
        self.refresh()

    def _track(self, start: int, end: int, positions: PositionMap) -> QTextCursor:
        """Kursor fragmentu; tekst dopisany tuż za fragmentem go nie wydłuża."""
        cursor = self.editor.track_range(start, end, positions)
        cursor.setKeepPositionOnInsert(True)
        return cursor

    def _changed(self) -> None:
        self.refresh()
        self._on_changed()

    def _index_of(self, comment_id: str) -> int:
        return next(
            index
            for index, item in enumerate(self.items)
            if item.comment.id == comment_id
        )
