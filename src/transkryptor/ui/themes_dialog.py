"""Okno „Pola tematyczne”: słowa kluczowe wywiadu w tematach (zgłoszenia #51, #71).

Okno pokazuje tabelę gotowych pól (liczy je ``ThemesController``) - pole,
słowo, liczba wystąpień, formy z tekstu i informatorzy, którzy użyli słowa.
Lista „Pole” zawęża tabelę do jednego pola (bez kolumny pola), a przycisk
„Dołącz transkrypcje…” prosi kontroler o dołączenie kolejnych projektów
(sygnał ``add_requested``). Tabelę można zapisać do CSV albo XLSX.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.catalog import CSV_SUFFIX, XLSX_SUFFIX, Table
from transkryptor.document.themes import ThemeSummary
from transkryptor.i18n import tr
from transkryptor.ui.table_export import export_table
from transkryptor.ui.theme import set_props

TEXTS = "themes"
ALL_FIELDS = ""


def themes_table(
    summaries: Sequence[ThemeSummary], theme_key: str = ALL_FIELDS
) -> Table:
    """Pola jako tabela do zapisu; przy wybranym polu - bez kolumny pola."""
    chosen = [s for s in summaries if theme_key in (ALL_FIELDS, s.theme.key)]
    words = (
        tr("themes.column.word"),
        tr("themes.column.count"),
        tr("themes.column.forms"),
        tr("themes.column.speakers"),
    )
    rows = [
        (
            summary.theme.label_text,
            word.lemma,
            word.count,
            ", ".join(word.forms),
            ", ".join(word.speakers),
        )
        for summary in chosen
        for word in summary.words
    ]
    if theme_key != ALL_FIELDS:
        return Table(words, tuple(row[1:] for row in rows))
    return Table((tr("themes.column.theme"), *words), tuple(rows))


class ThemesDialog(QDialog):
    """Tabela pól tematycznych z wyborem pola i zapisem do CSV/XLSX."""

    add_requested = Signal()

    def __init__(
        self,
        default_name: str,
        lemmatized: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("themes_dialog")
        self.setWindowTitle(tr("themes.title"))
        self._summaries: list[ThemeSummary] = []
        self._table = themes_table([])
        self._default_name = default_name
        self._build_layout(lemmatized)
        self._connect_signals()

    def _build_layout(self, lemmatized: bool) -> None:
        header = QLabel(tr("themes.header"))
        set_props(header, role="title")
        hint = QLabel(tr("themes.hint" if lemmatized else "themes.hint.plain"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.empty_label = QLabel(tr("themes.empty"))
        self.empty_label.setWordWrap(True)

        self.table = QTableWidget(0, 0)
        self.table.setObjectName("themes_table")
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.csv_button = self.buttons.addButton(
            tr("stats.export_csv"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.xlsx_button = self.buttons.addButton(
            tr("stats.export_xlsx"), QDialogButtonBox.ButtonRole.ActionRole
        )

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(hint)
        layout.addLayout(self._build_sources_row())
        layout.addWidget(self.empty_label)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.buttons)
        self.resize(760, 560)

    def _build_sources_row(self) -> QHBoxLayout:
        """Dołączone transkrypcje i wybór pola nad tabelą."""
        self.sources_label = QLabel()
        self.sources_label.setWordWrap(True)
        self.add_button = QPushButton(tr("themes.add"))
        self.add_button.setObjectName("themes_add_button")
        self.add_button.setToolTip(tr("themes.add.tooltip"))
        field_label = QLabel(tr("themes.field"))
        self.field_combo = QComboBox()
        self.field_combo.setObjectName("themes_field_combo")
        field_label.setBuddy(self.field_combo)
        row = QHBoxLayout()
        row.addWidget(self.sources_label, stretch=1)
        row.addWidget(self.add_button)
        row.addWidget(field_label)
        row.addWidget(self.field_combo)
        return row

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self.add_requested)
        self.field_combo.currentIndexChanged.connect(lambda _index: self._show())
        self.csv_button.clicked.connect(lambda: self.export(CSV_SUFFIX))
        self.xlsx_button.clicked.connect(lambda: self.export(XLSX_SUFFIX))
        self.buttons.rejected.connect(self.reject)

    def set_fields(self, summaries: list[ThemeSummary], sources: Sequence[str]) -> None:
        """Nowe pola i nazwy transkrypcji, z których je policzono."""
        self._summaries = summaries
        self.sources_label.setText(
            tr("themes.sources", count=len(sources), names=", ".join(sources))
        )
        chosen = self.field_combo.currentData() or ALL_FIELDS
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        self.field_combo.addItem(tr("themes.field.all"), ALL_FIELDS)
        for summary in summaries:
            self.field_combo.addItem(summary.theme.label_text, summary.theme.key)
        self.field_combo.setCurrentIndex(max(0, self.field_combo.findData(chosen)))
        self.field_combo.blockSignals(False)
        self._show()

    def select_field(self, theme_key: str) -> bool:
        """Zawęża tabelę do pola ``theme_key``; False - pola nie ma w wyniku."""
        index = self.field_combo.findData(theme_key)
        if index >= 0:
            self.field_combo.setCurrentIndex(index)
        return index >= 0

    def _show(self) -> None:
        self._table = themes_table(
            self._summaries, self.field_combo.currentData() or ALL_FIELDS
        )
        self.table.clear()
        self.table.setColumnCount(len(self._table.header))
        self.table.setRowCount(len(self._table.rows))
        self.table.setHorizontalHeaderLabels(list(self._table.header))
        for row, values in enumerate(self._table.rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        columns = self.table.horizontalHeader()
        columns.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        columns.setSectionResizeMode(
            len(self._table.header) - 1, QHeaderView.ResizeMode.Stretch
        )
        self.empty_label.setVisible(not self._table.rows)
        for button in (self.csv_button, self.xlsx_button):
            button.setEnabled(bool(self._table.rows))

    @property
    def header(self) -> tuple[str, ...]:
        return self._table.header

    @property
    def rows(self) -> tuple[tuple[object, ...], ...]:
        return self._table.rows

    def export(self, suffix: str) -> bool:
        """Zapis widocznej tabeli do CSV albo XLSX; False - anulowano albo błąd."""
        return export_table(self, self._table, self._default_name, suffix, TEXTS)
