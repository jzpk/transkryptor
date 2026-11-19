"""Propozycje reguł fonetycznych z poprawek szkicu ASR.

Kontroler zbiera poprawki słów szkicu - kotwice słów (``SyncController``)
pamiętają tekst słowa po wstawieniu szkicu i regułach, a różny tekst
w edytorze to poprawka transkrybenta - i po przerwie w pisaniu szuka
powtarzalnych zmian (``notation/learning.py``). Gdy ta sama zmiana
powtórzyła się kilka razy, w pasku stanu pojawia się przycisk z propozycją:
kliknięcie otwiera edytor reguł z gotową regułą (podgląd i liczba dopasowań
są już w edytorze), a menu przycisku pozwala odrzucić propozycję. Odrzucenie
zapisuje plik reguł użytkownika (``RulesStore.set_dismissed``), więc trafia
do profilu notacji i nie wraca po ponownym uruchomieniu (zgłoszenie #74).
Kontrolery mogą dołożyć do menu własne polecenia (:meth:`add_menu_action`,
np. okno wszystkich wniosków z poprawek).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton

from transkryptor.document.anchors import WORD
from transkryptor.document.model import Document
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.learning import (
    Candidate,
    Correction,
    candidates,
    display_change,
)
from transkryptor.notation.rules import PhoneticRule
from transkryptor.ui import icons
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.rules_store import RulesStore
from transkryptor.ui.sync_controller import SyncController

logger = logging.getLogger(__name__)

# Szukanie wzorców po przerwie w pisaniu (nie przy każdym klawiszu).
LEARNING_DEBOUNCE_MS = 1500


class RuleLearningController(QObject):
    """Poprawki szkicu, propozycja reguły w pasku stanu i jej utworzenie."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        sync: SyncController,
        document: Callable[[], Document],
        rules: RulesStore,
        create_rule: Callable[[PhoneticRule], object],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._sync = sync
        self._document = document
        self._rules = rules
        self._create_rule = create_rule
        # Odrzucenia, których nie udało się zapisać (do końca pracy programu).
        self._dismissed: set[tuple[str, str, str]] = set()
        self.candidate: Candidate | None = None

        self.button = QToolButton()
        self.button.setObjectName("learned_rule_button")
        self.button.setAutoRaise(True)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        icons.set_icon(self.button, "info", "accent", "text_muted")
        self.button.clicked.connect(self.create)
        menu = self.menu = QMenu(self.button)
        self.create_action = menu.addAction(tr("learning.create"))
        self.create_action.triggered.connect(lambda _checked=False: self.create())
        self.dismiss_action = menu.addAction(tr("learning.dismiss"))
        self.dismiss_action.triggered.connect(lambda _checked=False: self.dismiss())
        self.button.setMenu(menu)
        self.button.hide()

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(LEARNING_DEBOUNCE_MS)
        self.timer.timeout.connect(self.refresh)
        editor.document().contentsChanged.connect(self.schedule)
        sync.anchors_changed.connect(self.schedule)

    def schedule(self) -> None:
        if self.candidate is not None or any(
            item.baseline is not None for item in self._sync.items
        ):
            self.timer.start()

    def corrections(self) -> list[Correction]:
        """Poprawione słowa szkicu z indeksem górnym względem słowa."""
        document = self._document()
        positions = self._editor.position_map()
        result: list[Correction] = []
        for item in self._sync.items:
            if (
                item.anchor.source != WORD
                or item.baseline is None
                or not item.cursor.hasSelection()
            ):
                continue
            corrected = item.cursor.selectedText()
            if corrected == item.baseline:
                continue
            start, end = self._editor.selection_range(item.cursor, positions)
            superscript = tuple(
                (max(a, start) - start, min(b, end) - start)
                for a, b in document.superscript_ranges
                if a < end and b > start
            )
            result.append(Correction(item.baseline, corrected, superscript))
        return result

    def refresh(self) -> None:
        """Szuka powtarzalnych poprawek i pokazuje najczęstszą propozycję."""
        self.timer.stop()
        dismissed = {*self._rules.dismissed, *self._dismissed}
        found = candidates(self.corrections(), self._rules.rules, dismissed)
        self.candidate = found[0] if found else None
        if self.candidate is None:
            self.button.hide()
            return
        change = display_change(self.candidate.change)
        self.button.setText(
            tr("learning.hint", change=change, count=self.candidate.count)
        )
        self.button.setToolTip(
            tr(
                "learning.hint.tooltip",
                change=change,
                count=self.candidate.count,
                pattern=self.candidate.rule.pattern,
                example=self.candidate.example,
            )
        )
        self.button.show()

    def create(self) -> None:
        """Otwiera edytor reguł z proponowaną regułą."""
        if self.candidate is None:
            return
        self._create_rule(self.candidate.rule)
        self.refresh()

    def dismiss(self) -> None:
        """Nie proponuje już tej zmiany (zapisane w profilu notacji)."""
        if self.candidate is None:
            return
        key = self.candidate.change.key
        try:
            self._rules.set_dismissed(key)
        except AppError as error:
            logger.warning("Dismissed rule proposal could not be saved: %s", error)
            self._dismissed.add(key)
        self.refresh()

    def add_menu_action(self, action: QAction) -> None:
        """Polecenie w menu przycisku propozycji (za oddzieleniem)."""
        self.menu.addSeparator()
        self.menu.addAction(action)

    def set_locked(self, locked: bool) -> None:
        self.button.setEnabled(not locked)
