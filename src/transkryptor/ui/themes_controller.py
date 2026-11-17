"""Polecenie „Pola tematyczne…”: liczenie pól i łączenie transkrypcji (#51, #71).

Pola liczy ``document/themes.py`` z bieżącego tekstu i z transkrypcji
dołączonych w oknie (projekty ``.transkr``) - przy przypisanych mówcach
tylko z wypowiedzi informatorów, osobno dla każdego informatora, żeby
przy słowie było widać, kto go użył. Dołączone projekty żyją tylko do
zamknięcia okna. Lematy podaje Morfeusz 2 (wczytywany przy pierwszym
otwarciu okna); bez niego liczą się tylko słowa w formie słownikowej,
o czym okno informuje.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QWidget

from transkryptor.document.model import Document
from transkryptor.document.parts_of_speech import AnalyserUnavailable
from transkryptor.document.project import (
    ProjectState,
    file_dialog_filter,
    load_project,
)
from transkryptor.document.themes import (
    Lemmatizer,
    TextSource,
    ThemeSummary,
    combined_fields,
    morfeusz_lemmatizer,
    plain_lemmatizer,
    speaker_sources,
)
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.messages import show_error
from transkryptor.ui.themes_dialog import ThemesDialog


@dataclass(frozen=True)
class _Joined:
    """Transkrypcja dołączona w oknie pól."""

    path: Path
    state: ProjectState


def _document_sources(document: Document, name: str) -> list[TextSource]:
    return speaker_sources(
        document.text, document.paragraph_speakers, document.speakers, name
    )


def _project_sources(joined: _Joined) -> list[TextSource]:
    state = joined.state
    return speaker_sources(
        state.text, state.paragraph_speakers, state.speakers, joined.path.stem
    )


class ThemesController(QObject):
    """Okno pól tematycznych bieżącej transkrypcji i dołączonych projektów."""

    def __init__(
        self,
        parent: QWidget,
        document: Callable[[], Document],
        default_name: Callable[[], str],
        project_path: Callable[[], Path | None] = lambda: None,
        lemmatizer_factory: Callable[[], Lemmatizer] = morfeusz_lemmatizer,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._document = document
        self._default_name = default_name
        self._project_path = project_path
        self._factory = lemmatizer_factory
        self._lemmatize: Lemmatizer | None = None
        self._joined: list[_Joined] = []
        self.action = QAction(tr("themes.action"), parent)
        self.action.setToolTip(tr("themes.action.tooltip"))
        self.action.triggered.connect(lambda _checked=False: self.show())
        # Tworzenie okna; testy podstawiają atrapę zamiast ``exec``.
        self.run: Callable[[ThemesDialog], int] = lambda dialog: dialog.exec()

    def _lemmatizer(self) -> tuple[Lemmatizer, bool]:
        """Analizator lematów i czy to Morfeusz (a nie same formy słów)."""
        if self._lemmatize is None:
            try:
                self._lemmatize = self._factory()
            except AnalyserUnavailable:
                self._lemmatize = plain_lemmatizer
        return self._lemmatize, self._lemmatize is not plain_lemmatizer

    def summaries(self) -> list[ThemeSummary]:
        """Pola bieżącej transkrypcji i dołączonych projektów razem."""
        lemmatize, _ = self._lemmatizer()
        sources = _document_sources(self._document(), self._default_name())
        for joined in self._joined:
            sources.extend(_project_sources(joined))
        return combined_fields(sources, lemmatize)

    def source_names(self) -> list[str]:
        return [self._default_name(), *(j.path.stem for j in self._joined)]

    def show(self) -> None:
        self._joined = []
        _, lemmatized = self._lemmatizer()
        dialog = ThemesDialog(
            f"{self._default_name()}{tr('themes.name_suffix')}",
            lemmatized,
            self._parent,
        )
        dialog.add_requested.connect(lambda: self.choose_projects(dialog))
        self._refresh(dialog)
        self.run(dialog)
        self._joined = []

    def choose_projects(self, dialog: ThemesDialog) -> int:
        """Okno wyboru projektów do dołączenia; zwraca liczbę dołączonych."""
        paths, _selected = QFileDialog.getOpenFileNames(
            dialog, tr("themes.add.dialog"), "", file_dialog_filter()
        )
        return self.join_projects(dialog, (Path(path) for path in paths))

    def join_projects(self, dialog: ThemesDialog, paths: Iterable[Path]) -> int:
        """Dołącza projekty (bez bieżącego i powtórzeń) i przelicza pola."""
        known = {joined.path.resolve() for joined in self._joined}
        current = self._project_path()
        if current is not None:
            known.add(current.resolve())
        added = 0
        for path in paths:
            if path.resolve() in known:
                continue
            try:
                state = load_project(path)
            except AppError as error:
                show_error(dialog, tr("themes.add.error"), error)
                continue
            known.add(path.resolve())
            self._joined.append(_Joined(path, state))
            added += 1
        if added:
            self._refresh(dialog)
        return added

    def _refresh(self, dialog: ThemesDialog) -> None:
        dialog.set_fields(self.summaries(), self.source_names())
