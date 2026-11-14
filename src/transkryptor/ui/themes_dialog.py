"""Okno „Pola tematyczne”: słowa kluczowe wywiadu w tematach (zgłoszenie #51).

Pola liczy ``document/themes.py`` z bieżącego tekstu - przy przypisanych
mówcach tylko z wypowiedzi informatorów. Lematy podaje Morfeusz 2
(wczytywany przy pierwszym otwarciu okna); bez niego liczą się tylko słowa
w formie słownikowej, o czym okno informuje. Tabelę można zapisać do CSV
albo XLSX jak statystyki projektu.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.catalog import CSV_SUFFIX, XLSX_SUFFIX, Table
from transkryptor.document.model import Document
from transkryptor.document.parts_of_speech import AnalyserUnavailable
from transkryptor.document.speakers import informant_spans
from transkryptor.document.themes import (
    Lemmatizer,
    ThemeSummary,
    morfeusz_lemmatizer,
    plain_lemmatizer,
    thematic_fields,
)
from transkryptor.i18n import tr
from transkryptor.ui.table_export import export_table
from transkryptor.ui.theme import set_props

TEXTS = "themes"


def themes_table(summaries: list[ThemeSummary]) -> Table:
    """Pola jako tabela do zapisu: pole, słowo, wystąpienia, formy w tekście."""
    return Table(
        (
            tr("themes.column.theme"),
            tr("themes.column.word"),
            tr("themes.column.count"),
            tr("themes.column.forms"),
        ),
        tuple(
            (summary.theme.label_text, word.lemma, word.count, ", ".join(word.forms))
            for summary in summaries
            for word in summary.words
        ),
    )


def document_fields(document: Document, lemmatize: Lemmatizer) -> list[ThemeSummary]:
    """Pola tematyczne dokumentu; z mówcami - tylko wypowiedzi informatorów."""
    spans = informant_spans(
        document.text, document.paragraph_speakers, document.speakers
    )
    return thematic_fields(document.text, lemmatize, spans or None)


class ThemesDialog(QDialog):
    """Tabela pól tematycznych z zapisem do CSV/XLSX."""

    def __init__(
        self,
        summaries: list[ThemeSummary],
        default_name: str,
        lemmatized: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("themes_dialog")
        self.setWindowTitle(tr("themes.title"))
        self._table = themes_table(summaries)
        self._default_name = default_name
        self._build_layout(lemmatized)

    def _build_layout(self, lemmatized: bool) -> None:
        header = QLabel(tr("themes.header"))
        set_props(header, role="title")
        hint = QLabel(tr("themes.hint" if lemmatized else "themes.hint.plain"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.empty_label = QLabel(tr("themes.empty"))
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(not self._table.rows)

        self.table = QTableWidget(len(self._table.rows), len(self._table.header))
        self.table.setObjectName("themes_table")
        self.table.setHorizontalHeaderLabels(list(self._table.header))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, values in enumerate(self._table.rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        columns = self.table.horizontalHeader()
        columns.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        columns.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.csv_button = buttons.addButton(
            tr("stats.export_csv"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.xlsx_button = buttons.addButton(
            tr("stats.export_xlsx"), QDialogButtonBox.ButtonRole.ActionRole
        )
        for button in (self.csv_button, self.xlsx_button):
            button.setEnabled(bool(self._table.rows))
        self.csv_button.clicked.connect(lambda: self.export(CSV_SUFFIX))
        self.xlsx_button.clicked.connect(lambda: self.export(XLSX_SUFFIX))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(hint)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(buttons)
        self.resize(640, 520)

    @property
    def rows(self) -> tuple[tuple[object, ...], ...]:
        return self._table.rows

    def export(self, suffix: str) -> bool:
        """Zapis tabeli do CSV albo XLSX; False - anulowano albo błąd."""
        return export_table(self, self._table, self._default_name, suffix, TEXTS)


class ThemesController(QObject):
    """Polecenie „Pola tematyczne…” i analizator lematów."""

    def __init__(
        self,
        parent: QWidget,
        document: Callable[[], Document],
        default_name: Callable[[], str],
        lemmatizer_factory: Callable[[], Lemmatizer] = morfeusz_lemmatizer,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._document = document
        self._default_name = default_name
        self._factory = lemmatizer_factory
        self._lemmatize: Lemmatizer | None = None
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
        lemmatize, _ = self._lemmatizer()
        return document_fields(self._document(), lemmatize)

    def show(self) -> None:
        lemmatize, lemmatized = self._lemmatizer()
        dialog = ThemesDialog(
            document_fields(self._document(), lemmatize),
            f"{self._default_name()}{tr('themes.name_suffix')}",
            lemmatized,
            self._parent,
        )
        self.run(dialog)
