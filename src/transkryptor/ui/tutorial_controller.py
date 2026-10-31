"""Samouczki: uruchamianie przewodników, pierwsze uruchomienie i menu w pasku stanu.

Przy pierwszym uruchomieniu (``TutorialSettings.show_on_start``) startuje
samouczek „Pierwsze kroki”. Jego ukończenie albo pominięcie wyłącza ten
start - użytkownik wraca do samouczków przyciskiem
**Samouczki** w pasku stanu albo w ustawieniach (zakładka „Samouczki”).
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QToolButton, QWidget

from transkryptor.i18n import tr
from transkryptor.ui import icons
from transkryptor.ui.settings_store import SettingsStore
from transkryptor.ui.shortcuts import effective_shortcuts, native_shortcut
from transkryptor.ui.tutorial_content import FIRST_STEPS, TUTORIALS, TUTORIALS_BY_KEY
from transkryptor.ui.tutorial_overlay import TutorialOverlay

MODAL_RETRY_MS = 500


class TutorialController(QObject):
    """Nakładka samouczka okna ``host`` i przycisk z listą samouczków."""

    def __init__(
        self,
        host: QWidget,
        settings_store: SettingsStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_store = settings_store
        self.overlay = TutorialOverlay(host, self.shortcut_text)
        self.overlay.finished.connect(self._on_finished)
        self.button = self._build_button()
        # Samouczek z pierwszego uruchomienia - jego koniec wyłącza start.
        self._first_run = False

    def _build_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("tutorial_button")
        button.setText(tr("tutorial.button"))
        button.setToolTip(tr("tutorial.button.tooltip"))
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        icons.set_icon(button, "help", "text_muted", "text_muted")
        menu = QMenu(button)
        for tutorial in TUTORIALS:
            action = menu.addAction(tutorial.title)
            action.setToolTip(tutorial.summary)
            action.setData(tutorial.key)
            action.triggered.connect(
                lambda _checked=False, key=tutorial.key: self.start(key)
            )
        menu.setToolTipsVisible(True)
        button.setMenu(menu)
        return button

    def start(self, key: str) -> None:
        """Uruchamia samouczek ``key`` (nieznany klucz - nic się nie dzieje)."""
        tutorial = TUTORIALS_BY_KEY.get(key)
        if tutorial is not None:
            self._first_run = False
            self.overlay.start(tutorial)

    def start_first_run(self) -> None:
        """„Pierwsze kroki” przy starcie, dopóki ich nie ukończono ani nie pominięto."""
        if not self._settings_store.current.tutorial.show_on_start:
            return
        if QApplication.activeModalWidget() is not None:
            # Najpierw komunikaty startowe (np. odzyskanie pracy po awarii).
            QTimer.singleShot(MODAL_RETRY_MS, self.start_first_run)
            return
        if not self.is_running():
            self.start(FIRST_STEPS)
            self._first_run = True

    def is_running(self) -> bool:
        return self.overlay.is_running()

    def shortcut_text(self, action_id: str) -> str:
        """Bieżące skróty akcji w zapisie systemu, np. „Ctrl+Space / F4”."""
        overrides = self._settings_store.current.shortcuts.overrides
        sequences = effective_shortcuts(overrides).get(action_id, ())
        if not sequences:
            return tr("tutorial.no_shortcut")
        return " / ".join(native_shortcut(sequence) for sequence in sequences)

    def _on_finished(self, _completed: bool) -> None:
        first_run, self._first_run = self._first_run, False
        settings = self._settings_store.current
        if first_run and settings.tutorial.show_on_start:
            self._settings_store.save(
                replace(
                    settings, tutorial=replace(settings.tutorial, show_on_start=False)
                )
            )
