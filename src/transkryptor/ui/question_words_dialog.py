"""Okno „Słowa według pytań” (zgłoszenie #72).

Nad wynikiem są opcje liczenia - części mowy (kilka naraz) i tryb słów
wieloznacznych („Większa dokładność” albo „Pełniejsza lista”, opis w podpowiedzi
ikony informacji) - oraz filtry widoku: pytanie, kolejność, tylko słowa spoza
pól tematycznych i słowa nierozpoznane. Wynik jest w dwóch zakładkach: karty
pytań (:class:`~transkryptor.ui.question_words_cards.QuestionCards`) i tabela,
którą można zapisać do CSV albo XLSX. Zmiana opcji liczenia ogłasza
``options_changed`` (przelicza kontroler), a filtry działają od razu.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.catalog import CSV_SUFFIX, XLSX_SUFFIX
from transkryptor.document.parts_of_speech import PartOfSpeech
from transkryptor.document.question_words import QuestionWords, WordOptions
from transkryptor.i18n import tr
from transkryptor.ui import icons
from transkryptor.ui.question_words_cards import CardContext, QuestionCards
from transkryptor.ui.question_words_table import (
    ALL_QUESTIONS,
    PARTS,
    WordFilter,
    question_words_table,
    section_title,
    visible_sections,
)
from transkryptor.ui.table_export import export_table
from transkryptor.ui.theme import set_props

TEXTS = "question_words"


class QuestionWordsDialog(QDialog):
    """Słowa odpowiedzi według pytań z opcjami, filtrami i zapisem tabeli."""

    options_changed = Signal()
    refresh_requested = Signal()
    add_requested = Signal()

    def __init__(
        self,
        default_name: str,
        context: CardContext,
        available: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("question_words_dialog")
        self.setWindowTitle(tr("question_words.title"))
        self._default_name = default_name
        self._report = QuestionWords(())
        self.cards = QuestionCards(context)
        self._build_layout(available)
        self._connect_signals()
        self._show_mode_hint()

    # --- układ ---------------------------------------------------------------------

    def _build_layout(self, available: bool) -> None:
        header = QLabel(tr("question_words.header"))
        set_props(header, role="title")
        hint = QLabel(
            tr("question_words.hint" if available else "question_words.unavailable")
        )
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        set_props(self.notice_label, role="status", tone="warning")
        self.notice_label.hide()

        self.table = QTableWidget(0, 0)
        self.table.setObjectName("question_words_table")
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.cards, tr("question_words.tab.cards"))
        self.tabs.addTab(self.table, tr("question_words.tab.table"))

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
        layout.addLayout(self._build_parts_row())
        layout.addLayout(self._build_mode_row())
        layout.addLayout(self._build_filter_row())
        layout.addWidget(self.notice_label)
        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(self.buttons)
        self.resize(900, 720)

    def _build_sources_row(self) -> QHBoxLayout:
        self.sources_label = QLabel()
        self.sources_label.setWordWrap(True)
        self.add_button = QPushButton(tr("themes.add"))
        self.add_button.setObjectName("question_words_add_button")
        self.add_button.setToolTip(tr("question_words.add.tooltip"))
        self.refresh_button = QPushButton(tr("question_words.refresh"))
        self.refresh_button.setToolTip(tr("question_words.refresh.tooltip"))
        row = QHBoxLayout()
        row.addWidget(self.sources_label, stretch=1)
        row.addWidget(self.refresh_button)
        row.addWidget(self.add_button)
        return row

    def _build_parts_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("question_words.parts")))
        self.part_buttons: dict[PartOfSpeech, QToolButton] = {}
        for part in PARTS:
            button = QToolButton()
            button.setText(tr(f"pos.{part.value}"))
            button.setCheckable(True)
            button.setChecked(part is PartOfSpeech.NOUN)
            self.part_buttons[part] = button
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_mode_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("question_words.mode")))
        self.exact_button = QToolButton()
        self.exact_button.setText(tr("question_words.mode.exact"))
        self.full_button = QToolButton()
        self.full_button.setText(tr("question_words.mode.full"))
        self.mode_group = QButtonGroup(self)
        for button in (self.exact_button, self.full_button):
            button.setCheckable(True)
            self.mode_group.addButton(button)
            row.addWidget(button)
        self.exact_button.setChecked(True)
        self.mode_info = QToolButton()
        self.mode_info.setObjectName("question_words_mode_info")
        self.mode_info.setAutoRaise(True)
        icons.set_icon(self.mode_info, "info", "text_muted", "text_muted")
        row.addWidget(self.mode_info)
        row.addStretch(1)
        return row

    def _build_filter_row(self) -> QHBoxLayout:
        self.question_combo = QComboBox()
        self.question_combo.setObjectName("question_words_question_combo")
        self.sort_combo = QComboBox()
        self.sort_combo.addItem(tr("question_words.sort.count"), False)
        self.sort_combo.addItem(tr("question_words.sort.alphabetical"), True)
        self.outside_box = QCheckBox(tr("question_words.outside_fields"))
        self.unrecognized_box = QCheckBox(tr("question_words.unrecognized"))
        self.unrecognized_box.setToolTip(tr("question_words.unrecognized.tooltip"))
        self.unrecognized_box.setChecked(True)
        row = QHBoxLayout()
        for caption, widget in (
            (tr("question_words.question"), self.question_combo),
            (tr("question_words.sort"), self.sort_combo),
        ):
            label = QLabel(caption)
            label.setBuddy(widget)
            row.addWidget(label)
            row.addWidget(widget)
        row.addWidget(self.outside_box)
        row.addWidget(self.unrecognized_box)
        row.addStretch(1)
        return row

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self.add_requested)
        self.refresh_button.clicked.connect(self.refresh_requested)
        for button in self.part_buttons.values():
            button.toggled.connect(self._on_part_toggled)
        self.mode_group.buttonToggled.connect(self._on_mode_toggled)
        self.question_combo.currentIndexChanged.connect(lambda _index: self._show())
        self.sort_combo.currentIndexChanged.connect(lambda _index: self._show())
        self.outside_box.toggled.connect(lambda _checked: self._show())
        self.unrecognized_box.toggled.connect(lambda _checked: self._show())
        self.csv_button.clicked.connect(lambda: self.export(CSV_SUFFIX))
        self.xlsx_button.clicked.connect(lambda: self.export(XLSX_SUFFIX))
        self.buttons.rejected.connect(self.reject)

    # --- opcje i filtr -------------------------------------------------------------

    def options(self) -> WordOptions:
        parts = frozenset(p for p, b in self.part_buttons.items() if b.isChecked())
        return WordOptions(parts, self.full_button.isChecked())

    def words_filter(self) -> WordFilter:
        question = self.question_combo.currentData()
        return WordFilter(
            question=ALL_QUESTIONS if question is None else question,
            alphabetical=bool(self.sort_combo.currentData()),
            outside_fields=self.outside_box.isChecked(),
            unrecognized=self.unrecognized_box.isChecked(),
        )

    def _on_part_toggled(self, checked: bool) -> None:
        if not checked and not any(b.isChecked() for b in self.part_buttons.values()):
            # Co najmniej jedna część mowy zostaje wybrana.
            button = self.sender()
            if isinstance(button, QToolButton):
                button.blockSignals(True)
                button.setChecked(True)
                button.blockSignals(False)
            return
        self.options_changed.emit()

    def _on_mode_toggled(self, _button: object, checked: bool) -> None:
        if checked:
            self._show_mode_hint()
            self.options_changed.emit()

    def _show_mode_hint(self) -> None:
        mode = "full" if self.full_button.isChecked() else "exact"
        text = tr(f"question_words.mode.{mode}.tooltip")
        self.mode_info.setToolTip(text)
        self.mode_info.setAccessibleDescription(text)

    def set_mode_full(self, full: bool) -> None:
        (self.full_button if full else self.exact_button).setChecked(True)

    def set_part(self, part: PartOfSpeech, checked: bool) -> None:
        self.part_buttons[part].setChecked(checked)

    # --- wynik ---------------------------------------------------------------------

    def set_report(self, report: QuestionWords, sources: Sequence[str]) -> None:
        """Nowy wynik i nazwy transkrypcji, z których go policzono."""
        self._report = report
        self.sources_label.setText(
            tr("themes.sources", count=len(sources), names=", ".join(sources))
        )
        chosen = self.question_combo.currentData()
        self.question_combo.blockSignals(True)
        self.question_combo.clear()
        self.question_combo.addItem(tr("question_words.question.all"), None)
        for section in report.sections:
            self.question_combo.addItem(section_title(section), section.number)
        index = self.question_combo.findData(chosen) if chosen is not None else 0
        self.question_combo.setCurrentIndex(max(0, index))
        self.question_combo.blockSignals(False)
        lost = ", ".join(str(mark.question + 1) for mark in report.lost_marks)
        self.notice_label.setText(tr("question_words.lost", numbers=lost))
        self.notice_label.setVisible(bool(lost))
        self._show()

    def _show(self) -> None:
        words_filter = self.words_filter()
        sections = visible_sections(self._report, words_filter)
        self._table = question_words_table(sections, words_filter)
        self.cards.show_report(self._report, words_filter)
        self.table.clear()
        self.table.setColumnCount(len(self._table.header))
        self.table.setRowCount(len(self._table.rows))
        self.table.setHorizontalHeaderLabels(list(self._table.header))
        for row, values in enumerate(self._table.rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        columns = self.table.horizontalHeader()
        columns.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for button in (self.csv_button, self.xlsx_button):
            button.setEnabled(bool(self._table.rows))

    @property
    def report(self) -> QuestionWords:
        return self._report

    @property
    def rows(self) -> tuple[tuple[object, ...], ...]:
        return self._table.rows

    def export(self, suffix: str) -> bool:
        """Zapis widocznej tabeli do CSV albo XLSX; False - anulowano albo błąd."""
        return export_table(self, self._table, self._default_name, suffix, TEXTS)
