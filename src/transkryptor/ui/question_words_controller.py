"""Polecenie „Słowa według pytań…”: liczenie, dołączanie projektów i wskazania (#72).

Słowa liczy ``document/question_words.py`` z bieżącej transkrypcji (z jej
kwestionariuszem i wskazaniami akapitów pytań) i z projektów dołączonych
w oknie, które żyją do zamknięcia okna (projekt bez własnego kwestionariusza
dzieli się pytaniami bieżącego). Okno jest niemodalne: transkrybent
może przejść do akapitu pytania w edytorze, ustawić tam kursor i wskazać go
jako akapit pytania. Wskazania zapisuje pole kwestionariusza panelu ASR
(``QuestionnaireAccess``), więc trafiają do projektu i oznaczają go jako
zmieniony. Części mowy podaje Morfeusz 2 (wczytywany przy pierwszym
otwarciu okna); bez niego okno informuje, że lista jest niedostępna.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QWidget

from transkryptor.document.model import Document
from transkryptor.document.parts_of_speech import (
    Analyser,
    AnalyserUnavailable,
    PartOfSpeechTagger,
    morfeusz_analyser,
)
from transkryptor.document.project import (
    ProjectState,
    file_dialog_filter,
    load_project,
)
from transkryptor.document.question_words import (
    Candidate,
    QuestionLocator,
    QuestionWords,
    WordsSource,
    question_words,
)
from transkryptor.document.questionnaire import QuestionMark
from transkryptor.document.speakers import paragraph_spans
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.messages import show_error
from transkryptor.ui.player_bar import format_ms
from transkryptor.ui.question_words_dialog import QuestionWordsDialog


class QuestionnaireAccess(Protocol):
    """Kwestionariusz projektu i wskazania akapitów pytań (panel ASR)."""

    def questionnaire(self) -> tuple[str, ...]: ...

    def question_marks(self) -> tuple[QuestionMark, ...]: ...

    def set_question_marks(self, marks: tuple[QuestionMark, ...]) -> None: ...


class ProjectSource(Protocol):
    """Bieżący dokument i projekt (``SessionController``)."""

    @property
    def document(self) -> Document: ...

    @property
    def project_name(self) -> str | None: ...

    @property
    def project_path(self) -> Path | None: ...


class TimeSource(Protocol):
    def time_span(self, start: int, end: int) -> tuple[int, int] | None: ...


def _state_source(
    path: Path, state: ProjectState, questions: tuple[str, ...]
) -> WordsSource:
    """Dołączony projekt; bez własnego kwestionariusza - pytania bieżącego."""
    context = state.asr_context
    return WordsSource(
        path.stem,
        state.text,
        state.paragraph_speakers,
        state.speakers,
        context.questionnaire or questions,
        context.question_marks if context.questionnaire else (),
    )


class QuestionWordsController(QObject):
    """Okno słów według pytań bieżącej transkrypcji i dołączonych projektów."""

    def __init__(
        self,
        parent: QWidget,
        project: ProjectSource,
        questionnaire: QuestionnaireAccess,
        editor: TranscriptionEditor,
        times: TimeSource,
        analyser_factory: Callable[[], Analyser] = morfeusz_analyser,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._project = project
        self._questionnaire = questionnaire
        self._editor = editor
        self._times = times
        self._factory = analyser_factory
        self._tagger: PartOfSpeechTagger | None = None
        self._available = True
        self._joined: list[tuple[Path, ProjectState]] = []
        self.dialog: QuestionWordsDialog | None = None
        self.action = QAction(tr("question_words.action"), parent)
        self.action.setToolTip(tr("question_words.action.tooltip"))
        self.action.triggered.connect(lambda _checked=False: self.show())
        # Pokazanie okna; testy podstawiają atrapę zamiast ``show``.
        self.run: Callable[[QuestionWordsDialog], None] = lambda dialog: dialog.show()

    # --- dane ----------------------------------------------------------------------

    def _tagger_or_none(self) -> PartOfSpeechTagger | None:
        if self._tagger is None and self._available:
            try:
                self._tagger = PartOfSpeechTagger(self._factory())
            except AnalyserUnavailable:
                self._available = False
        return self._tagger

    def current_source(self) -> WordsSource:
        document = self._project.document
        return WordsSource(
            self.default_name(),
            document.text,
            document.paragraph_speakers,
            document.speakers,
            self._questionnaire.questionnaire(),
            self._questionnaire.question_marks(),
        )

    def default_name(self) -> str:
        return Path(self._project.project_name or tr("stats.default_name")).stem

    def report(self) -> QuestionWords:
        tagger = self._tagger_or_none()
        if tagger is None or self.dialog is None:
            return QuestionWords(())
        current = self.current_source()
        sources = [current]
        sources.extend(
            _state_source(path, state, current.questions)
            for path, state in self._joined
        )
        return question_words(sources, tagger, self.dialog.options())

    def source_names(self) -> list[str]:
        return [self.default_name(), *(path.stem for path, _ in self._joined)]

    # --- CardContext ------------------------------------------------------------------

    def candidates(self, question: int) -> list[Candidate]:
        return QuestionLocator(self.current_source()).candidates(question)

    def paragraph_label(self, paragraph: int) -> str:
        spans = paragraph_spans(self._project.document.text)
        if 0 <= paragraph < len(spans):
            span = self._times.time_span(*spans[paragraph])
            if span is not None:
                return format_ms(span[0])
        return tr("question_words.paragraph", number=paragraph + 1)

    # --- okno ----------------------------------------------------------------------

    def show(self) -> None:
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self._joined = []
        self._tagger_or_none()
        dialog = QuestionWordsDialog(
            f"{self.default_name()}{tr('question_words.name_suffix')}",
            self,
            self._available,
            self._parent,
        )
        self.dialog = dialog
        dialog.options_changed.connect(self.refresh)
        dialog.refresh_requested.connect(self.refresh)
        dialog.add_requested.connect(self.choose_projects)
        dialog.cards.mark_requested.connect(self.mark)
        dialog.cards.cursor_mark_requested.connect(self.mark_cursor)
        dialog.cards.unmark_requested.connect(self.unmark)
        dialog.cards.go_to_requested.connect(self.go_to)
        dialog.finished.connect(self._closed)
        self.refresh()
        self.run(dialog)

    def _closed(self, _result: int = 0) -> None:
        if self.dialog is not None:
            self.dialog.deleteLater()
        self.dialog = None
        self._joined = []

    def refresh(self) -> None:
        if self.dialog is not None:
            self.dialog.set_report(self.report(), self.source_names())

    def choose_projects(self) -> int:
        """Okno wyboru projektów do dołączenia; zwraca liczbę dołączonych."""
        paths, _selected = QFileDialog.getOpenFileNames(
            self.dialog, tr("themes.add.dialog"), "", file_dialog_filter()
        )
        return self.join_projects(Path(path) for path in paths)

    def join_projects(self, paths: Iterable[Path]) -> int:
        """Dołącza projekty (bez bieżącego i powtórzeń) i przelicza słowa."""
        known = {path.resolve() for path, _ in self._joined}
        current = self._project.project_path
        if current is not None:
            known.add(current.resolve())
        added = 0
        for path in paths:
            if path.resolve() in known:
                continue
            try:
                state = load_project(path)
            except AppError as error:
                show_error(self.dialog or self._parent, tr("themes.add.error"), error)
                continue
            known.add(path.resolve())
            self._joined.append((path, state))
            added += 1
        if added:
            self.refresh()
        return added

    # --- wskazania akapitów pytań ------------------------------------------------------

    def mark(self, question: int, paragraph: int) -> None:
        """Akapit ``paragraph`` to pytanie ``question`` (numer od 0)."""
        spans = paragraph_spans(self._project.document.text)
        if not 0 <= paragraph < len(spans):
            return
        start, end = spans[paragraph]
        text = self._project.document.text[start:end].strip()
        if not text:
            return
        marks = [
            mark
            for mark in self._questionnaire.question_marks()
            if mark.question != question and mark.paragraph.strip() != text
        ]
        marks.append(QuestionMark(question, text))
        self._questionnaire.set_question_marks(tuple(marks))
        self.refresh()

    def mark_cursor(self, question: int) -> None:
        """Akapit z kursorem edytora to pytanie ``question``."""
        self.mark(question, self._editor.textCursor().blockNumber())

    def unmark(self, question: int) -> None:
        """Pytanie wraca do rozpoznania automatycznego."""
        marks = self._questionnaire.question_marks()
        self._questionnaire.set_question_marks(
            tuple(mark for mark in marks if mark.question != question)
        )
        self.refresh()

    def go_to(self, paragraph: int) -> None:
        """Zaznacza akapit w edytorze (okno słów zostaje otwarte)."""
        spans = paragraph_spans(self._project.document.text)
        if 0 <= paragraph < len(spans):
            self._editor.setTextCursor(self._editor.track_range(*spans[paragraph]))
            self._editor.ensureCursorVisible()

    def set_locked(self, locked: bool) -> None:
        self.action.setEnabled(not locked)
        if self.dialog is not None:
            self.dialog.setEnabled(not locked)
