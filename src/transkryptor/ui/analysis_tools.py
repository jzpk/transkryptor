"""Okna analizy słownictwa w menu eksportu: pola tematyczne i słowa według pytań.

Oba polecenia liczą słowa bieżącej transkrypcji (i projektów dołączonych
w oknie) - ``AnalysisTools`` tylko je składa z zależności okna, żeby
``MainWindow`` nie rosło z każdym kolejnym zestawieniem.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction

from transkryptor.i18n import tr
from transkryptor.ui.question_words_controller import QuestionWordsController
from transkryptor.ui.themes_controller import ThemesController

if TYPE_CHECKING:
    from transkryptor.ui.main_window import MainWindow


class AnalysisTools:
    """Kontrolery zestawień słów i ich akcje w menu eksportu."""

    def __init__(self, window: MainWindow) -> None:
        session = window.session
        self.themes = ThemesController(
            window,
            lambda: session.document,
            lambda: Path(session.project_name or tr("stats.default_name")).stem,
            lambda: session.project_path,
        )
        self.question_words = QuestionWordsController(
            window, session, window.asr_panel, window.editor, window.sync
        )

    @property
    def actions(self) -> list[QAction]:
        return [self.themes.action, self.question_words.action]

    def set_locked(self, locked: bool) -> None:
        self.themes.action.setEnabled(not locked)
        self.question_words.set_locked(locked)
