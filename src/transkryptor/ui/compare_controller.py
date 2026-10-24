"""Porównanie bieżącego projektu z drugim plikiem projektu (faza 14, REQ-27).

``CompareController`` otwiera drugi projekt tego samego nagrania, liczy
zmiany (``document/diff.py``) i pokazuje obie wersje obok siebie: po lewej
bieżący dokument (wynik porównania), po prawej wersję porównywaną tylko do
odczytu. Zmiany są podświetlone w obu kolumnach (warstwa ``COMPARE_LAYER``)
i wymienione w panelu (``ui/compare_panel.py``).

Na czas porównania lewy edytor jest tylko do odczytu — tekst zmieniają
wyłącznie „Przyjmij” i cofanie, więc zakresy zmian się nie rozjeżdżają.
Przyjęcie i odrzucenie to polecenia własnego ``QUndoStack`` (ACC-63):
przyjęcie wstawia fragment wersji B w miejsce fragmentu A (z indeksem
górnym i mówcami akapitów), a cofnięcie wstawia z powrotem fragment A;
odrzucenie zmienia tylko stan pozycji. Porównanie nie jest zapisywane
w projekcie — po zakończeniu zostaje bieżący dokument.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QTextCursor,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from transkryptor.document.anchors import Anchor, anchor_at
from transkryptor.document.diff import (
    DELETE,
    FORMAT,
    INSERT,
    REPLACE,
    SPEAKER,
    Change,
    Fragment,
    Version,
    diff_versions,
    fragment,
    replaced_speakers,
)
from transkryptor.document.model import Document
from transkryptor.document.project import (
    ProjectState,
    file_dialog_filter,
    load_project,
)
from transkryptor.document.speakers import Speaker
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.compare_panel import (
    ACCEPTED,
    PENDING,
    REJECTED,
    ComparePanel,
    change_label,
)
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import COMPARE_LAYER, background, solid_underline
from transkryptor.ui.messages import show_error
from transkryptor.ui.sync_controller import SyncController
from transkryptor.ui.theme import tokens

UNDO_SHORTCUT = "Ctrl+Z"
REDO_SHORTCUT = "Ctrl+Shift+Z"
# Przezroczystość podświetleń zmian (czytelne w obu motywach).
CHANGE_ALPHA = 70


@dataclass
class CompareItem:
    """Zmiana z kursorami w obu kolumnach i fragmentami do przyjęcia i cofnięcia.

    Kursor lewej kolumny obejmuje bieżący tekst zmiany: fragment A albo — po
    przyjęciu — wstawiony fragment B.
    """

    change: Change
    cursor: QTextCursor
    other: QTextCursor
    before: Fragment
    after: Fragment
    state: str = PENDING


class _Accept(QUndoCommand):
    def __init__(self, controller: CompareController, item: CompareItem) -> None:
        super().__init__(tr("compare.undo.accept"))
        self._controller = controller
        self._item = item

    def redo(self) -> None:
        self._controller._set_fragment(self._item, accepted=True)
        self._item.state = ACCEPTED
        self._controller.refresh()

    def undo(self) -> None:
        self._controller._set_fragment(self._item, accepted=False)
        self._item.state = PENDING
        self._controller.refresh()


class _Reject(QUndoCommand):
    def __init__(self, controller: CompareController, item: CompareItem) -> None:
        super().__init__(tr("compare.undo.reject"))
        self._controller = controller
        self._item = item

    def redo(self) -> None:
        self._item.state = REJECTED
        self._controller.refresh()

    def undo(self) -> None:
        self._item.state = PENDING
        self._controller.refresh()


class CompareController(QObject):
    """Tryb porównania dwóch wersji: lista zmian, decyzje i cofanie."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        view: TranscriptionEditor,
        show_column: Callable[[str | None], None],
        sync: SyncController,
        document: Callable[[], Document],
        add_speakers: Callable[[list[Speaker]], None],
        audio_sha256: Callable[[], str | None],
        show_status: Callable[[str], None],
        dialog_parent: QWidget,
    ) -> None:
        super().__init__(dialog_parent)
        self.editor = editor
        self.view = view
        self._show_column = show_column
        self._sync = sync
        self._document = document
        self._add_speakers = add_speakers
        self._audio_sha256 = audio_sha256
        self._show_status = show_status
        self._parent = dialog_parent
        self.items: list[CompareItem] = []
        self._other: ProjectState | None = None
        self.stack = QUndoStack(self)
        self.undo_action = self._stack_action(
            self.stack.createUndoAction(self, tr("compare.undo")), UNDO_SHORTCUT
        )
        self.redo_action = self._stack_action(
            self.stack.createRedoAction(self, tr("compare.redo")), REDO_SHORTCUT
        )
        self.panel = ComparePanel(self.undo_action, self.redo_action)
        self.panel.item_activated.connect(self.activate)
        self.panel.accept_requested.connect(self.accept)
        self.panel.reject_requested.connect(self.reject)
        self.panel.play_requested.connect(self.play)
        self.panel.accept_all_requested.connect(self.accept_all)
        self.panel.reject_all_requested.connect(self.reject_all)
        self.panel.finish_requested.connect(self.finish)

    def _stack_action(self, action: QAction, shortcut: str) -> QAction:
        action.setShortcut(QKeySequence(shortcut))
        # Skrót działa w całym oknie; poza porównaniem stos jest pusty, a
        # wyłączona akcja nie zabiera skrótu edytorowi.
        self._parent.addAction(action)
        return action

    @property
    def active(self) -> bool:
        return self._other is not None

    # --- start i koniec ---------------------------------------------------

    def compare_dialog(self) -> bool:
        """„Porównaj z…”: wybór drugiego projektu i start porównania."""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self._parent, tr("compare.dialog"), "", file_dialog_filter()
        )
        return bool(path) and self.compare_with(path)

    def compare_with(self, path: str | Path) -> bool:
        """Porównuje bieżący dokument z projektem ``path``; False — bez porównania."""
        source = Path(path)
        try:
            other = load_project(source)
        except AppError as error:
            show_error(self._parent, tr("compare.error"), error)
            return False
        current_sha = self._audio_sha256()
        if (
            current_sha
            and other.audio is not None
            and other.audio.sha256
            and other.audio.sha256 != current_sha
        ):
            answer = QMessageBox.question(
                self._parent,
                tr("compare.other_audio.title"),
                tr("compare.other_audio.text", name=source.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.finish()
        current = Version.from_document(self._document())
        other_version = Version(
            other.text, other.superscript_ranges, dict(other.paragraph_speakers)
        )
        changes = diff_versions(current, other_version)
        if not changes:
            QMessageBox.information(
                self._parent,
                tr("compare.title.short"),
                tr("compare.identical", name=source.name),
            )
            return False

        self._other = other
        self.view.load_content(
            other.text, other.superscript_ranges, other.paragraph_speakers
        )
        positions = self.editor.position_map()
        other_positions = self.view.position_map()
        self.items = [
            CompareItem(
                change,
                self.editor.track_range(change.a_start, change.a_end, positions),
                self.view.track_range(change.b_start, change.b_end, other_positions),
                fragment(current, change.a_start, change.a_end),
                fragment(other_version, change.b_start, change.b_end),
            )
            for change in changes
        ]
        self.editor.setReadOnly(True)
        self.panel.set_title(source.name)
        self._show_column(source.name)
        self.refresh()
        self.panel.select(0)
        self.activate(0)
        return True

    def finish(self) -> None:
        """Kończy porównanie; nierozpatrzone zmiany zostają odrzucone."""
        if not self.active:
            return
        self._other = None
        self.items = []
        self.stack.clear()
        self.editor.set_highlight_layer(COMPARE_LAYER, [])
        self.view.set_highlight_layer(COMPARE_LAYER, [])
        self.view.clear()
        self.editor.setReadOnly(False)
        self.panel.set_items([])
        self._show_column(None)

    # --- decyzje ----------------------------------------------------------

    def accept(self, index: int) -> None:
        item = self.items[index]
        if item.state != PENDING or not self._can_accept(item):
            return
        self.stack.push(_Accept(self, item))

    def reject(self, index: int) -> None:
        item = self.items[index]
        if item.state == PENDING:
            self.stack.push(_Reject(self, item))

    def accept_all(self) -> None:
        """Przyjmuje wszystkie oczekujące zmiany jednym krokiem cofania."""
        pending = [
            item
            for item in self.items
            if item.state == PENDING and self._can_accept(item, quiet=True)
        ]
        if not pending:
            return
        self.stack.beginMacro(tr("compare.undo.accept_all"))
        for item in pending:
            self.stack.push(_Accept(self, item))
        self.stack.endMacro()

    def reject_all(self) -> None:
        pending = [item for item in self.items if item.state == PENDING]
        if not pending:
            return
        self.stack.beginMacro(tr("compare.undo.reject_all"))
        for item in pending:
            self.stack.push(_Reject(self, item))
        self.stack.endMacro()

    def _can_accept(self, item: CompareItem, quiet: bool = False) -> bool:
        """Czy fragment w lewej kolumnie jest nadal taki jak przy porównaniu.

        Zmiany się nie nakładają poza zmianą mówcy (cały akapit), ale
        przyjęcie zmiany obok może zmienić granice — wtedy pozycja czeka.
        """
        if item.change.kind == SPEAKER:
            return True
        positions = self.editor.position_map()
        start, end = self.editor.selection_range(item.cursor, positions)
        if positions.text[start:end] == item.before.text:
            return True
        if not quiet:
            QMessageBox.information(
                self._parent, tr("compare.title.short"), tr("compare.stale")
            )
        return False

    def _set_fragment(self, item: CompareItem, accepted: bool) -> None:
        """Wstawia fragment B (przyjęcie) albo A (cofnięcie) jednym blokiem edycji."""
        if item.change.kind == SPEAKER:
            key = item.change.b_speaker if accepted else item.change.a_speaker
            self._ensure_speakers([key])
            start, _end = self.editor.selection_range(item.cursor)
            edit = QTextCursor(self.editor.document())
            edit.beginEditBlock()
            self.editor.assign_paragraph_speakers(start, [key])
            edit.endEditBlock()
            return
        new = item.after if accepted else item.before
        positions = self.editor.position_map()
        text = positions.text
        start, end = self.editor.selection_range(item.cursor, positions)
        current = Version(text, (), self.editor.paragraph_speakers(text))
        keys = replaced_speakers(current, start, end, new)
        self._ensure_speakers(keys)
        self._sync.loosen()
        edit = QTextCursor(self.editor.document())
        edit.beginEditBlock()
        self.editor.apply_tracked_replacements(
            [(item.cursor, new.text, new.superscript_ranges)]
        )
        self.editor.assign_paragraph_speakers(start, keys)
        edit.endEditBlock()
        self._sync.settle()

    def _ensure_speakers(self, keys: list[str | None]) -> None:
        """Dopisuje do bieżącej listy mówców brakujących mówców wersji B."""
        if self._other is None:
            return
        known = {speaker.key for speaker in self._document().speakers}
        missing = [
            speaker
            for speaker in self._other.speakers
            if speaker.key in keys and speaker.key not in known
        ]
        if missing:
            self._add_speakers(missing)

    # --- przejście i odsłuch ---------------------------------------------

    def activate(self, index: int) -> None:
        """Zaznacza zmianę w obu kolumnach i przewija do niej obie."""
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        for editor, cursor in ((self.editor, item.cursor), (self.view, item.other)):
            editor.setTextCursor(QTextCursor(cursor))
            editor.ensureCursorVisible()
        self.editor.setFocus()

    def play(self, index: int) -> None:
        """Odsłuch zmiany: kotwica bieżącego tekstu albo — gdy jej brak — wersji B."""
        item = self.items[index]
        start, _end = self.editor.selection_range(item.cursor)
        anchor: Anchor | None = self._sync.anchor_at(start)
        if anchor is None and self._other is not None:
            anchor = anchor_at(self._other.anchors, item.change.b_start)
        if anchor is None:
            self._show_status(tr("sync.no_anchor"))
            return
        self._sync.play_anchor(anchor)

    # --- widok ------------------------------------------------------------

    def refresh(self) -> None:
        """Podświetlenia oczekujących zmian w obu kolumnach i lista w panelu."""
        t = tokens()
        colors = {
            INSERT: QColor(t.success),
            DELETE: QColor(t.danger),
            REPLACE: QColor(t.warning),
            SPEAKER: QColor(t.accent),
        }
        for color in colors.values():
            color.setAlpha(CHANGE_ALPHA)
        accent = QColor(t.accent)
        mine = []
        theirs = []
        for item in self.items:
            if item.state != PENDING:
                continue
            kind = item.change.kind
            if kind == FORMAT:
                mine.append(solid_underline(QTextCursor(item.cursor), accent))
                theirs.append(solid_underline(QTextCursor(item.other), accent))
                continue
            color = colors[kind]
            if item.cursor.hasSelection() and kind != INSERT:
                mine.append(background(QTextCursor(item.cursor), color))
            if item.other.hasSelection() and kind != DELETE:
                theirs.append(background(QTextCursor(item.other), color))
        self.editor.set_highlight_layer(COMPARE_LAYER, mine)
        self.view.set_highlight_layer(COMPARE_LAYER, theirs)
        self.panel.set_items([(self._label(item), item.state) for item in self.items])

    def _label(self, item: CompareItem) -> str:
        change = item.change
        if change.kind == SPEAKER:
            return change_label(SPEAKER, change.a_speaker or "", change.b_speaker or "")
        return change_label(change.kind, item.before.text, item.after.text)
