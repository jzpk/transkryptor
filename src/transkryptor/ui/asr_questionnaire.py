"""Kwestionariusz wywiadu w panelu ASR: wczytanie z pliku i stan (zgłoszenie #47).

Pytania z kwestionariusza są zapisywane w projekcie razem z kontekstem
nagrania i słownikiem. Układ szkicu „pytanie - odpowiedź” rozpoznaje dzięki
nim wypowiedzi badacza także bez znaku zapytania.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from transkryptor.document.questionnaire import read_questionnaire
from transkryptor.errors import AppError
from transkryptor.i18n import tr, tr_plural
from transkryptor.ui import icons
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props


class QuestionnaireBox(QWidget):
    """Wiersz „Kwestionariusz: N pytań” z wczytaniem i usunięciem."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._questions: tuple[str, ...] = ()
        self.status_label = QLabel()
        set_props(self.status_label, role="muted")
        self.load_button = QPushButton(tr("asr.questionnaire.load"))
        self.load_button.setObjectName("asr_questionnaire_button")
        self.load_button.setToolTip(tr("asr.questionnaire.tooltip"))
        self.load_button.clicked.connect(self._choose_file)
        self.clear_button = QToolButton()
        icons.set_icon(self.clear_button, "close", "text_muted")
        self.clear_button.setAutoRaise(True)
        self.clear_button.setToolTip(tr("asr.questionnaire.clear"))
        self.clear_button.clicked.connect(lambda: self.set_questions((), notify=True))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status_label, stretch=1)
        layout.addWidget(self.load_button)
        layout.addWidget(self.clear_button)
        self._show_state()

    def questions(self) -> tuple[str, ...]:
        return self._questions

    def set_questions(
        self, questions: tuple[str, ...], *, notify: bool = False
    ) -> None:
        self._questions = tuple(questions)
        self._show_state()
        if notify:
            self.changed.emit()

    def load(self, path: Path) -> bool:
        """Wczytuje pytania z pliku; błąd albo pusty plik - komunikat."""
        try:
            questions = read_questionnaire(path)
        except (OSError, ValueError, KeyError) as error:
            show_error(
                self,
                tr("asr.questionnaire.error.title"),
                AppError(
                    tr("asr.questionnaire.error", name=path.name),
                    tr("asr.questionnaire.error.hint") + f" ({error})",
                ),
            )
            return False
        if not questions:
            show_error(
                self,
                tr("asr.questionnaire.error.title"),
                AppError(
                    tr("asr.questionnaire.empty", name=path.name),
                    tr("asr.questionnaire.error.hint"),
                ),
            )
            return False
        self.set_questions(questions, notify=True)
        return True

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("asr.questionnaire.dialog"),
            "",
            tr("asr.questionnaire.filter"),
        )
        if path:
            self.load(Path(path))

    def _show_state(self) -> None:
        count = len(self._questions)
        self.status_label.setText(
            tr_plural("asr.questionnaire.count", count)
            if count
            else tr("asr.questionnaire.none")
        )
        self.status_label.setToolTip("\n".join(self._questions[:20]))
        self.clear_button.setVisible(bool(count))
