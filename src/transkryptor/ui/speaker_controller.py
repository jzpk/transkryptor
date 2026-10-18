"""Mówcy akapitów: skróty, menu i lista mówców nagrania (propozycja 15).

Przypisanie mówcy to format bloku edytora (jeden krok cofania), a lista
mówców — dane dokumentu (``Document.speakers``) edytowane w oknie
``ui/speakers_dialog.py``. Skrót ``Alt+Shift+N`` przypisuje bieżącemu
akapitowi (albo akapitom zaznaczenia) N-tego mówcę z listy; ponowne użycie
zdejmuje przypisanie, ``Alt+Shift+0`` usuwa mówcę.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QWidget

from transkryptor.document.model import Document
from transkryptor.document.speakers import Speaker, legend
from transkryptor.i18n import tr
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.metadata_form import MetadataForm
from transkryptor.ui.shortcuts import (
    SHORTCUT_ACTIONS_BY_ID,
    SPEAKER_CLEAR_ID,
    SPEAKER_COUNT,
    speaker_id,
)
from transkryptor.ui.speakers_dialog import SpeakersDialog


class SpeakerController(QObject):
    """Akcje przypisania mówców i edycja listy mówców dokumentu."""

    # Lista mówców się zmieniła (tytuł okna, walidacja, licznik słów).
    speakers_changed = Signal()

    def __init__(
        self,
        editor: TranscriptionEditor,
        document: Callable[[], Document],
        metadata_form: MetadataForm,
        show_message: Callable[[str], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._document = document
        self._form = metadata_form
        self._show_message = show_message
        self._parent = parent
        self.actions: dict[str, QAction] = {}
        editor.context_menu_extenders.append(self.extend_context_menu)
        editor.speaker_label_clicked.connect(self._on_label_clicked)
        metadata_form.speakers_edit_requested.connect(self.edit_speakers)

    def create_actions(self, owner: QWidget) -> dict[str, QAction]:
        """Akcje skrótów (zasięg aplikacji, jak wyszukiwanie)."""
        for number in range(1, SPEAKER_COUNT + 1):
            self.actions[speaker_id(number)] = self._action(
                owner, speaker_id(number), partial(self.assign_number, number)
            )
        self.actions[SPEAKER_CLEAR_ID] = self._action(
            owner, SPEAKER_CLEAR_ID, self.clear
        )
        return self.actions

    def _action(
        self, owner: QWidget, action_id: str, handler: Callable[[], None]
    ) -> QAction:
        definition = SHORTCUT_ACTIONS_BY_ID[action_id]
        action = QAction(definition.label, owner)
        action.setShortcuts([QKeySequence(s) for s in definition.defaults])
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        action.triggered.connect(lambda _checked=False: handler())
        owner.addAction(action)
        return action

    def set_locked(self, locked: bool) -> None:
        for action in self.actions.values():
            action.setEnabled(not locked)

    # --- przypisanie ---------------------------------------------------------

    def assign_number(self, number: int) -> None:
        speakers = self._document().speakers
        if not 1 <= number <= len(speakers):
            self._show_message(tr("speakers.no_speaker", number=number))
            return
        self.assign(speakers[number - 1].key)

    def assign(self, key: str | None) -> None:
        self._editor.set_paragraph_speaker(key)

    def clear(self) -> None:
        self._editor.set_paragraph_speaker(None)

    def _speaker_menu(self, menu: QMenu, current: str | None) -> None:
        for number, speaker in enumerate(self._document().speakers, start=1):
            text = f"{speaker.key} — {speaker.description}"
            shortcut = self.actions.get(speaker_id(number))
            if shortcut is not None and not shortcut.shortcut().isEmpty():
                native = shortcut.shortcut().toString(
                    QKeySequence.SequenceFormat.NativeText
                )
                text = f"{text}\t{native}"
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(speaker.key == current)
            action.triggered.connect(
                lambda _checked=False, key=speaker.key: self._editor.set_paragraph_speaker(
                    None if key == current else key
                )
            )
        menu.addSeparator()
        none_action = menu.addAction(tr("speakers.menu.none"))
        none_action.setEnabled(current is not None)
        none_action.triggered.connect(lambda _checked=False: self.clear())
        menu.addSeparator()
        edit = menu.addAction(tr("speakers.menu.edit"))
        edit.triggered.connect(lambda _checked=False: self.edit_speakers())

    def extend_context_menu(self, menu: QMenu, position: int) -> None:
        menu.addSeparator()
        submenu = menu.addMenu(tr("speakers.menu"))
        self._speaker_menu(submenu, self._editor.speaker_at(position))

    def _on_label_clicked(self, position: int, global_pos: QPoint) -> None:
        menu = QMenu(self._editor)
        self._speaker_menu(menu, self._editor.speaker_at(position))
        self.exec_menu(menu, global_pos)
        menu.deleteLater()

    def exec_menu(self, menu: QMenu, global_pos: QPoint) -> None:
        """Pokazuje menu modalnie (testy podmieniają tę metodę)."""
        menu.exec(global_pos)

    # --- lista mówców ----------------------------------------------------------

    def edit_speakers(self) -> None:
        document = self._document()
        dialog = SpeakersDialog(
            document.speakers, set(document.paragraph_speakers.values()), self._parent
        )
        if dialog.exec() != SpeakersDialog.DialogCode.Accepted:
            return
        self.apply_speakers(dialog.speakers(), dialog.renamed(), dialog.removed())

    def apply_speakers(
        self,
        speakers: list[Speaker],
        renamed: dict[str, str] | None = None,
        removed: set[str] | None = None,
    ) -> None:
        """Nowa lista mówców; akapity idą za zmianą klucza, usunięci tracą mówcę."""
        renamed = renamed or {}
        mapping: dict[str, str | None] = dict(renamed)
        mapping.update({key: None for key in removed or ()})
        self._document().set_speakers(speakers, renamed)
        self._editor.remap_speakers(mapping)
        self.refresh()
        self.speakers_changed.emit()

    def refresh(self) -> None:
        """Legenda w metryczce i kolumna etykiet po zmianie dokumentu."""
        self._form.set_speakers_summary(legend(self._document().speakers))
        self._editor.refresh_speakers()
