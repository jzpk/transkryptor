"""„Sprawdź tekst” - gotowa transkrypcja według bieżących reguł szkicu (zgł. #62).

Projekt zrobiony przed aktualizacją nie przeszedł przez obróbkę szkicu
z nowszych wersji, a ponowna transkrypcja nagrania trwa godzinami
i zastąpiłaby poprawki transkrybenta. Kontroler sprawdza sam tekst
edytora, bez modelu ASR:

- reguły fonetyczne (wbudowane, własne i zapisane reguły nauczone) oraz
  zapis szkicu z ustawień (``asr/recheck.py``) trafiają na listę przeglądu
  w panelu ASR jako propozycje - nic nie zmienia się bez decyzji
  użytkownika;
- akapity bez mówcy mogą dostać mówców według układu „pytanie -
  odpowiedź” (pytanie - badacz, reszta - informator) po potwierdzeniu,
  jednym krokiem cofania;
- powtarzalne poprawki szkicu w tym projekcie od razu dają propozycję
  nowej reguły (przycisk na pasku stanu, ``RuleLearningController``).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox

from transkryptor.asr.qa_layout import question_detector
from transkryptor.asr.recheck import question_answer_speakers, style_suggestions
from transkryptor.document.model import Document
from transkryptor.document.speakers import INFORMANT, RESEARCHER
from transkryptor.i18n import tr
from transkryptor.settings import AsrSettings
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.draft_styler import DraftStyler
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.review import ReviewController


class RecheckController(QObject):
    """Propozycje reguł szkicu dla tekstu, który już jest w edytorze."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        review: ReviewController,
        panel: AsrPanel,
        document: Callable[[], Document],
        flush_editor: Callable[[], object],
        settings: Callable[[], AsrSettings],
        refresh_learning: Callable[[], None],
        show_status: Callable[[str], None],
    ) -> None:
        super().__init__(panel)
        self._editor = editor
        self._review = review
        self._panel = panel
        self._document = document
        self._flush_editor = flush_editor
        self._refresh_learning = refresh_learning
        self._show_status = show_status
        self._styler = DraftStyler(settings)
        panel.recheck_requested.connect(self.recheck)

    def recheck(self) -> None:
        """Sprawdza tekst edytora: propozycje, mówcy i nauczone reguły."""
        text = self._editor.plain_text()
        if not text.strip():
            self._show_status(tr("recheck.empty"))
            return
        # Indeks górny i mówcy z bieżącego tekstu (synchronizacja bywa opóźniona).
        self._flush_editor()
        document = self._document()
        count = self._review.review_text(
            style_suggestions(text, self._styler.style()),
            document.superscript_ranges,
        )
        self._panel.show_review()
        self._assign_speakers(text, document)
        self._refresh_learning()
        self._show_status(tr("recheck.done", count=count))

    def _assign_speakers(self, text: str, document: Document) -> None:
        keys = _role_keys(document)
        if keys is None:
            return
        question_key, answer_key = keys
        speakers = question_answer_speakers(
            text,
            document.paragraph_speakers,
            question_detector(self._panel.questionnaire()),
            question_key,
            answer_key,
        )
        if not speakers or not self._confirm_speakers(speakers, keys):
            return
        assigned = {**document.paragraph_speakers, **speakers}
        paragraphs = text.count("\n") + 1
        edit = QTextCursor(self._editor.document())
        edit.beginEditBlock()
        self._editor.assign_paragraph_speakers(
            0, [assigned.get(index) for index in range(paragraphs)], text
        )
        edit.endEditBlock()

    def _confirm_speakers(
        self, speakers: dict[int, str], keys: tuple[str, str]
    ) -> bool:
        question_key, answer_key = keys
        answer = QMessageBox.question(
            self._editor.window(),
            tr("recheck.speakers.title"),
            tr(
                "recheck.speakers.text",
                count=len(speakers),
                questions=sum(key == question_key for key in speakers.values()),
                question_key=question_key,
                answer_key=answer_key,
            ),
        )
        return answer == QMessageBox.StandardButton.Yes


def _role_keys(document: Document) -> tuple[str, str] | None:
    """Klucze pierwszego badacza i pierwszego informatora z listy mówców."""
    researcher = next((s.key for s in document.speakers if s.role == RESEARCHER), None)
    informant = next((s.key for s in document.speakers if s.role == INFORMANT), None)
    if researcher is None or informant is None:
        return None
    return researcher, informant
