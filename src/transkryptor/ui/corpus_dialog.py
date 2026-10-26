"""Okno „Korpus”: praca na wszystkich projektach folderu.

Trzy zakładki:

- **Wyszukiwanie** - słowo, forma albo wyrażenie regularne we wszystkich
  projektach folderu (``corpus/concordance.py``): konkordancja z kontekstem,
  mówcą i czasem, odsłuch fragmentu i przejście do miejsca w projekcie;
- **Słownik form** - unikalne formy bieżącego projektu albo całego folderu
  z liczbą wystąpień, formami podobnymi (``corpus/forms.py``) i listą
  wystąpień wybranej formy; lista form trafia do CSV albo XLSX;
- **Metryczki** - katalog nagrań (``corpus/catalog.py``) do CSV, XLSX albo
  TEI XML (``corpus/tei.py``), także w wersji anonimizowanej.

Okno nie jest modalne. Ma własny odtwarzacz (odsłuch fragmentów innych
projektów nie zmienia nagrania okna głównego - to na czas odsłuchu pauzuje).
Bieżący projekt jest czytany ze stanu edytora (z niezapisanymi zmianami),
pozostałe - z plików. Otwieranie projektów i zaznaczanie tekstu robi
``ui/corpus_controller.py`` przez :class:`CorpusHost`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QFont, QHideEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.audio.player import AudioPlayer
from transkryptor.corpus.catalog import (
    CSV_SUFFIX,
    XLSX_SUFFIX,
    Table,
    catalog_table,
    forms_table,
    save_table,
)
from transkryptor.corpus.concordance import Hit, concordance, make_hit
from transkryptor.corpus.forms import FormEntry, form_index, similar_forms
from transkryptor.corpus.projects import CorpusProject, ScanResult, scan_folder
from transkryptor.corpus.tei import TEI_SUFFIX, save_tei
from transkryptor.document.metadata import MetadataField
from transkryptor.document.search import SearchError, SearchOptions, compile_query
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.messages import show_error
from transkryptor.ui.player_bar import format_ms
from transkryptor.ui.theme import set_props

# Margines odsłuchu przed i po fragmencie (czasy słów są ciasne).
CLIP_MARGIN_MS = 400
SEARCH_TAB, FORMS_TAB, CATALOG_TAB = range(3)
SCOPE_CURRENT, SCOPE_FOLDER = "current", "folder"


@dataclass(frozen=True)
class CorpusHost:
    """Połączenie okna korpusu z oknem głównym."""

    # Bieżący dokument jako projekt korpusu (stan edytora).
    current_project: Callable[[], CorpusProject]
    fields: Callable[[], tuple[MetadataField, ...]]
    go_to: Callable[[CorpusProject, int, int], object]
    pause_main: Callable[[], None]


class HitTable(QTableWidget):
    """Konkordancja: projekt, mówca, kontekst, trafienie, kontekst, czas."""

    PROJECT, SPEAKER, LEFT, MATCH, RIGHT, TIME = range(6)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(
            [
                tr("corpus.hits.project"),
                tr("corpus.hits.speaker"),
                tr("corpus.hits.left"),
                tr("corpus.hits.match"),
                tr("corpus.hits.right"),
                tr("corpus.hits.time"),
            ]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        for column in (self.PROJECT, self.SPEAKER, self.MATCH, self.TIME):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (self.LEFT, self.RIGHT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self._hits: list[Hit] = []

    @property
    def hits(self) -> list[Hit]:
        return list(self._hits)

    def set_hits(self, hits: Sequence[Hit], folder: Path | None) -> None:
        self._hits = list(hits)
        self.setUpdatesEnabled(False)
        self.clearContents()
        self.setRowCount(len(self._hits))
        bold = QFont(self.font())
        bold.setBold(True)
        for row, hit in enumerate(self._hits):
            project = QTableWidgetItem(hit.project.relative_name(folder))
            if hit.project.path is not None:
                project.setToolTip(str(hit.project.path))
            left = QTableWidgetItem(hit.left)
            left.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            match = QTableWidgetItem(hit.match)
            match.setFont(bold)
            time = QTableWidgetItem(
                "" if hit.time_ms is None else format_ms(hit.time_ms[0])
            )
            for column, item in (
                (self.PROJECT, project),
                (self.SPEAKER, QTableWidgetItem(hit.speaker)),
                (self.LEFT, left),
                (self.MATCH, match),
                (self.RIGHT, QTableWidgetItem(hit.right)),
                (self.TIME, time),
            ):
                self.setItem(row, column, item)
        self.setUpdatesEnabled(True)
        if self._hits:
            self.selectRow(0)

    def current_hit(self) -> Hit | None:
        row = self.currentRow()
        if 0 <= row < len(self._hits):
            return self._hits[row]
        return None


def _table_widget(columns: Sequence[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    return table


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    set_props(label, role="muted")
    return label


def _item(value: str | int) -> QTableWidgetItem:
    item = QTableWidgetItem()
    # Liczby jako liczby - sortowanie kolumny po wartości, nie po tekście.
    item.setData(Qt.ItemDataRole.DisplayRole, value)
    return item


class CorpusDialog(QDialog):
    def __init__(self, host: CorpusHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("corpus.title"))
        self.setModal(False)
        self.resize(1080, 680)
        self._host = host
        self.folder: Path | None = None
        self.scan: ScanResult | None = None
        self.player = AudioPlayer(self)
        self._playing: Hit | None = None
        self._forms: list[FormEntry] = []
        self._similar: dict[str, tuple[str, ...]] = {}
        self._forms_project: CorpusProject | None = None
        self._catalog: Table | None = None

        self.folder_label = _muted(tr("corpus.folder.none"))
        self.choose_button = QPushButton(tr("corpus.folder.choose"))
        self.choose_button.clicked.connect(self.choose_folder)
        self.refresh_button = QPushButton(tr("corpus.folder.refresh"))
        self.refresh_button.setToolTip(tr("corpus.folder.refresh.tooltip"))
        self.refresh_button.clicked.connect(self.refresh)
        self.summary_label = _muted()
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("corpus.folder")))
        top.addWidget(self.folder_label, stretch=1)
        top.addWidget(self.summary_label)
        top.addWidget(self.choose_button)
        top.addWidget(self.refresh_button)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_search_tab(), tr("corpus.tab.search"))
        self.tabs.addTab(self._build_forms_tab(), tr("corpus.tab.forms"))
        self.tabs.addTab(self._build_catalog_tab(), tr("corpus.tab.catalog"))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.play_button = QPushButton(tr("corpus.play"))
        self.play_button.setToolTip(tr("corpus.play.tooltip"))
        self.play_button.clicked.connect(self.toggle_play)
        self.go_button = QPushButton(tr("corpus.go_to"))
        self.go_button.setToolTip(tr("corpus.go_to.tooltip"))
        self.go_button.clicked.connect(self.go_to_selected)
        self.status_label = _muted()
        close_button = QPushButton(tr("corpus.close"))
        close_button.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self.play_button)
        bottom.addWidget(self.go_button)
        bottom.addWidget(self.status_label, stretch=1)
        bottom.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tabs, stretch=1)
        layout.addLayout(bottom)

        self.player.playback_state_changed.connect(self._on_playback_state)
        self._update_buttons()

    # --- budowa zakładek ----------------------------------------------------

    def _build_search_tab(self) -> QWidget:
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(tr("corpus.search.placeholder"))
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.returnPressed.connect(self.run_search)
        self.case_check = QCheckBox(tr("corpus.case_sensitive"))
        self.words_check = QCheckBox(tr("search.whole_words"))
        self.words_check.setChecked(True)
        self.regex_check = QCheckBox(tr("corpus.regex"))
        self.informant_check = QCheckBox(tr("corpus.informant_only"))
        self.informant_check.setToolTip(tr("corpus.informant_only.tooltip"))
        self.search_button = QPushButton(tr("corpus.search.run"))
        self.search_button.clicked.connect(self.run_search)
        row = QHBoxLayout()
        row.addWidget(self.query_edit, stretch=1)
        row.addWidget(self.search_button)
        options = QHBoxLayout()
        for check in (
            self.case_check,
            self.words_check,
            self.regex_check,
            self.informant_check,
        ):
            options.addWidget(check)
        options.addStretch(1)
        self.hits_table = HitTable()
        self.hits_table.itemSelectionChanged.connect(self._update_buttons)
        self.hits_table.itemActivated.connect(lambda _item: self.go_to_selected())
        self.hits_label = _muted(tr("corpus.search.hint"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addLayout(row)
        layout.addLayout(options)
        layout.addWidget(self.hits_label)
        layout.addWidget(self.hits_table, stretch=1)
        return page

    def _build_forms_tab(self) -> QWidget:
        self.scope_combo = QComboBox()
        self.scope_combo.addItem(tr("corpus.forms.scope.current"), SCOPE_CURRENT)
        self.scope_combo.addItem(tr("corpus.forms.scope.folder"), SCOPE_FOLDER)
        self.scope_combo.currentIndexChanged.connect(self.refresh_forms)
        self.forms_case_check = QCheckBox(tr("corpus.case_sensitive"))
        self.forms_case_check.toggled.connect(self.refresh_forms)
        self.forms_informant_check = QCheckBox(tr("corpus.informant_only"))
        self.forms_informant_check.setToolTip(tr("corpus.informant_only.tooltip"))
        self.forms_informant_check.toggled.connect(self.refresh_forms)
        self.similar_check = QCheckBox(tr("corpus.forms.similar_only"))
        self.similar_check.setToolTip(tr("corpus.forms.similar_only.tooltip"))
        self.similar_check.toggled.connect(self._fill_forms)
        self.forms_filter_edit = QLineEdit()
        self.forms_filter_edit.setPlaceholderText(tr("corpus.forms.filter"))
        self.forms_filter_edit.setClearButtonEnabled(True)
        self.forms_filter_edit.textChanged.connect(self._fill_forms)
        self.export_forms_button = QToolButton()
        self.export_forms_button.setText(tr("corpus.forms.export"))
        self.export_forms_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        forms_menu = QMenu(self.export_forms_button)
        forms_menu.addAction(
            tr("corpus.export.csv"), lambda: self.export_forms(CSV_SUFFIX)
        )
        forms_menu.addAction(
            tr("corpus.export.xlsx"), lambda: self.export_forms(XLSX_SUFFIX)
        )
        self.export_forms_button.setMenu(forms_menu)
        options = QHBoxLayout()
        options.addWidget(QLabel(tr("corpus.forms.scope")))
        options.addWidget(self.scope_combo)
        options.addWidget(self.forms_case_check)
        options.addWidget(self.forms_informant_check)
        options.addWidget(self.similar_check)
        options.addWidget(self.forms_filter_edit, stretch=1)
        options.addWidget(self.export_forms_button)

        self.forms_table = _table_widget(
            [
                tr("corpus.forms.form"),
                tr("corpus.forms.count"),
                tr("corpus.forms.projects"),
                tr("corpus.forms.similar"),
            ]
        )
        header = self.forms_table.horizontalHeader()
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.forms_table.itemSelectionChanged.connect(self._on_form_selected)
        self.forms_table.itemActivated.connect(self._on_form_activated)
        self.forms_label = _muted()
        self.occurrences_table = HitTable()
        self.occurrences_table.itemSelectionChanged.connect(self._update_buttons)
        self.occurrences_table.itemActivated.connect(
            lambda _item: self.go_to_selected()
        )
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.forms_table)
        splitter.addWidget(self.occurrences_table)
        splitter.setSizes([320, 200])
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addLayout(options)
        layout.addWidget(self.forms_label)
        layout.addWidget(splitter, stretch=1)
        return page

    def _build_catalog_tab(self) -> QWidget:
        self.anonymize_check = QCheckBox(tr("corpus.catalog.anonymize"))
        self.anonymize_check.setToolTip(tr("corpus.catalog.anonymize.tooltip"))
        self.anonymize_check.toggled.connect(self.refresh_catalog)
        self.export_csv_button = QPushButton(tr("corpus.export.csv"))
        self.export_csv_button.clicked.connect(lambda: self.export_catalog(CSV_SUFFIX))
        self.export_xlsx_button = QPushButton(tr("corpus.export.xlsx"))
        self.export_xlsx_button.clicked.connect(
            lambda: self.export_catalog(XLSX_SUFFIX)
        )
        self.export_tei_button = QPushButton(tr("corpus.export.tei"))
        self.export_tei_button.setToolTip(tr("corpus.export.tei.tooltip"))
        self.export_tei_button.clicked.connect(self.export_tei)
        row = QHBoxLayout()
        row.addWidget(self.anonymize_check)
        row.addStretch(1)
        row.addWidget(self.export_csv_button)
        row.addWidget(self.export_xlsx_button)
        row.addWidget(self.export_tei_button)
        self.catalog_table = _table_widget([])
        self.catalog_label = _muted(tr("corpus.catalog.hint"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addLayout(row)
        layout.addWidget(self.catalog_label)
        layout.addWidget(self.catalog_table, stretch=1)
        return page

    # --- folder i skan ------------------------------------------------------

    @property
    def projects(self) -> tuple[CorpusProject, ...]:
        return self.scan.projects if self.scan is not None else ()

    def choose_folder(self) -> None:
        start = str(self.folder) if self.folder is not None else ""
        chosen = QFileDialog.getExistingDirectory(
            self, tr("corpus.folder.dialog"), start
        )
        if chosen:
            self.set_folder(Path(chosen))

    def set_folder(self, folder: Path | None, scan: bool = True) -> None:
        self.folder = folder
        self.folder_label.setText(
            str(folder) if folder is not None else tr("corpus.folder.none")
        )
        self.folder_label.setToolTip(str(folder) if folder is not None else "")
        if scan:
            self.refresh()

    def refresh(self) -> None:
        """Czyta projekty folderu na nowo i odświeża wszystkie zakładki."""
        if self.folder is None:
            self.scan = None
            self.summary_label.setText("")
        else:
            current = self._host.current_project()
            overrides = {} if current.path is None else {current.path: current.state}
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.scan = scan_folder(self.folder, overrides)
            finally:
                QApplication.restoreOverrideCursor()
            self._show_summary(self.scan)
        if self.query_edit.text().strip():
            self.run_search()
        else:
            self.hits_table.set_hits([], self.folder)
        self.refresh_forms()
        self.refresh_catalog()

    def _show_summary(self, scan: ScanResult) -> None:
        text = tr("corpus.folder.summary", count=len(scan.projects))
        if scan.errors:
            text = tr(
                "corpus.folder.summary_errors", text=text, errors=len(scan.errors)
            )
            self.summary_label.setToolTip(
                "\n".join(f"{e.path.name}: {e.message}" for e in scan.errors)
            )
        else:
            self.summary_label.setToolTip("")
        self.summary_label.setText(text)

    # --- wyszukiwanie -------------------------------------------------------

    def run_search(self) -> None:
        query = self.query_edit.text()
        if not query.strip():
            self.hits_table.set_hits([], self.folder)
            self.hits_label.setText(tr("corpus.search.hint"))
            return
        if self.scan is None:
            self.hits_label.setText(tr("corpus.folder.needed"))
            return
        options = SearchOptions(
            case_sensitive=self.case_check.isChecked(),
            whole_words=self.words_check.isChecked(),
            regex=self.regex_check.isChecked(),
        )
        try:
            pattern = compile_query(query, options)
            result = concordance(
                self.projects, pattern, self.informant_check.isChecked()
            )
        except SearchError as error:
            self.hits_table.set_hits([], self.folder)
            self.hits_label.setText(str(error))
            return
        self.hits_table.set_hits(result.hits, self.folder)
        text = tr(
            "corpus.search.result",
            hits=len(result.hits),
            projects=result.project_count,
        )
        if result.truncated:
            text = tr("corpus.search.truncated", text=text)
        self.hits_label.setText(text)
        self._update_buttons()

    # --- słownik form -------------------------------------------------------

    def refresh_forms(self) -> None:
        if self.scope_combo.currentData() == SCOPE_CURRENT:
            self._forms_project = self._host.current_project()
            projects: Sequence[CorpusProject] = (self._forms_project,)
        elif self.scan is None:
            self._forms, self._similar = [], {}
            self._fill_forms()
            self.forms_label.setText(tr("corpus.folder.needed"))
            return
        else:
            projects = self.projects
        self._forms = form_index(
            projects,
            case_sensitive=self.forms_case_check.isChecked(),
            informant_only=self.forms_informant_check.isChecked(),
        )
        self._similar = similar_forms(entry.form for entry in self._forms)
        self._fill_forms()

    def visible_forms(self) -> list[FormEntry]:
        """Formy po filtrze (fragment formy) i opcji „tylko z podobnymi”."""
        needle = self.forms_filter_edit.text().strip().casefold()
        similar_only = self.similar_check.isChecked()
        return [
            entry
            for entry in self._forms
            if (not needle or needle in entry.form.casefold())
            and (not similar_only or entry.form in self._similar)
        ]

    def _fill_forms(self) -> None:
        forms = self.visible_forms()
        table = self.forms_table
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        table.clearContents()
        table.setRowCount(len(forms))
        for row, entry in enumerate(forms):
            form = _item(entry.form)
            form.setData(Qt.ItemDataRole.UserRole, entry.form)
            table.setItem(row, 0, form)
            table.setItem(row, 1, _item(entry.count))
            table.setItem(row, 2, _item(entry.project_count))
            table.setItem(row, 3, _item(", ".join(self._similar.get(entry.form, ()))))
        table.setUpdatesEnabled(True)
        table.setSortingEnabled(True)
        total = sum(entry.count for entry in self._forms)
        self.forms_label.setText(
            tr(
                "corpus.forms.summary",
                forms=len(self._forms),
                words=total,
                shown=len(forms),
            )
        )
        self.occurrences_table.set_hits([], self.folder)
        if forms:
            table.selectRow(0)
        self._update_buttons()

    def selected_form(self) -> FormEntry | None:
        items = self.forms_table.selectedItems()
        if not items:
            return None
        form_item = self.forms_table.item(items[0].row(), 0)
        if form_item is None:
            return None
        form = form_item.data(Qt.ItemDataRole.UserRole)
        return next((entry for entry in self._forms if entry.form == form), None)

    def select_form(self, form: str) -> bool:
        """Zaznacza formę na liście (np. formę podobną); False - nie ma jej."""
        for row in range(self.forms_table.rowCount()):
            item = self.forms_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == form:
                self.forms_table.selectRow(row)
                self.forms_table.scrollToItem(item)
                return True
        return False

    def _on_form_selected(self) -> None:
        entry = self.selected_form()
        hits = (
            []
            if entry is None
            else [
                make_hit(occurrence.project, occurrence.start, occurrence.end)
                for occurrence in entry.occurrences
            ]
        )
        self.occurrences_table.set_hits(hits, self.folder)
        self._update_buttons()

    def _on_form_activated(self, item: QTableWidgetItem) -> None:
        """Dwuklik w kolumnie form podobnych przechodzi do pierwszej z nich."""
        if item.column() != 3:
            return
        entry = self.selected_form()
        similar = self._similar.get(entry.form, ()) if entry is not None else ()
        if similar and not self.select_form(similar[0]):
            self.forms_filter_edit.clear()
            self.similar_check.setChecked(False)
            self.select_form(similar[0])

    def export_forms(self, suffix: str) -> None:
        if not self._forms:
            self.status_label.setText(tr("corpus.forms.empty"))
            return
        name = (
            self._forms_project.name
            if self.scope_combo.currentData() == SCOPE_CURRENT
            and self._forms_project is not None
            else (self.folder.name if self.folder is not None else "")
        )
        table = forms_table(self.visible_forms(), self._similar)
        self._save(table, tr("corpus.forms.default_name", name=name), suffix)

    # --- katalog ------------------------------------------------------------

    def refresh_catalog(self) -> None:
        table = self.catalog_table
        if self.scan is None:
            self._catalog = None
            table.clear()
            table.setColumnCount(0)
            table.setRowCount(0)
            self._update_buttons()
            return
        catalog = catalog_table(
            self.projects,
            self._host.fields(),
            anonymize=self.anonymize_check.isChecked(),
            folder=self.folder,
        )
        self._catalog = catalog
        table.setSortingEnabled(False)
        table.clear()
        table.setColumnCount(len(catalog.header))
        table.setHorizontalHeaderLabels(list(catalog.header))
        table.setRowCount(len(catalog.rows))
        for row, values in enumerate(catalog.rows):
            for column, value in enumerate(values):
                table.setItem(
                    row, column, _item(value if isinstance(value, int) else str(value))
                )
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)
        self._update_buttons()

    def export_catalog(self, suffix: str) -> None:
        if self._catalog is None or not self._catalog.rows:
            self.status_label.setText(tr("corpus.catalog.empty"))
            return
        name = self.folder.name if self.folder is not None else ""
        self._save(self._catalog, tr("corpus.catalog.default_name", name=name), suffix)

    def export_tei(self) -> None:
        if not self.projects:
            self.status_label.setText(tr("corpus.catalog.empty"))
            return
        folder = self.folder
        name = folder.name if folder is not None else ""
        path = self._ask_path(tr("corpus.tei.default_name", name=name), TEI_SUFFIX)
        if path is None:
            return
        try:
            save_tei(
                self.projects,
                path,
                self._host.fields(),
                anonymize=self.anonymize_check.isChecked(),
                title=name,
                folder=folder,
            )
        except AppError as error:
            show_error(self, tr("corpus.export.error"), error)
            return
        self.status_label.setText(tr("corpus.export.done", name=path.name))

    def _ask_path(self, default_name: str, suffix: str) -> Path | None:
        folder = self.folder if self.folder is not None else Path.home()
        return ask_save_path(
            self,
            tr("corpus.export.dialog"),
            str(folder / f"{default_name}{suffix}"),
            tr(f"corpus.export.filter{suffix}", pattern=f"*{suffix}"),
            suffix,
        )

    def _save(self, table: Table, default_name: str, suffix: str) -> None:
        path = self._ask_path(default_name, suffix)
        if path is None:
            return
        try:
            save_table(table, path)
        except AppError as error:
            show_error(self, tr("corpus.export.error"), error)
            return
        self.status_label.setText(tr("corpus.export.done", name=path.name))

    # --- odsłuch i przejście ------------------------------------------------

    def current_hit(self) -> Hit | None:
        index = self.tabs.currentIndex()
        if index == SEARCH_TAB:
            return self.hits_table.current_hit()
        if index == FORMS_TAB:
            return self.occurrences_table.current_hit()
        return None

    def toggle_play(self) -> None:
        hit = self.current_hit()
        if self.player.is_playing and (hit is None or hit is self._playing):
            self.player.pause()
            return
        if hit is not None:
            self.play_hit(hit)

    def play_hit(self, hit: Hit) -> bool:
        """Odtwarza fragment trafienia w pętli (do pauzy); False - nie da się."""
        if hit.time_ms is None:
            self.status_label.setText(tr("corpus.play.no_time"))
            return False
        audio = hit.project.audio_path()
        if audio is None:
            self.status_label.setText(tr("corpus.play.no_audio"))
            return False
        if self.player.source_path != audio:
            try:
                self.player.load(audio)
            except AppError as error:
                show_error(self, tr("main.playback_error"), error)
                return False
        self._host.pause_main()
        start, end = hit.time_ms
        self._playing = hit
        self.player.play_loop_once(max(0, start - CLIP_MARGIN_MS), end + CLIP_MARGIN_MS)
        self.status_label.setText(
            tr(
                "corpus.play.playing",
                name=hit.project.name,
                start=format_ms(start),
                end=format_ms(end),
            )
        )
        return True

    def go_to_selected(self) -> None:
        hit = self.current_hit()
        if hit is None:
            return
        self.player.pause()
        self._host.go_to(hit.project, hit.start, hit.end)

    def _on_playback_state(self, playing: bool) -> None:
        self.play_button.setText(tr("corpus.stop") if playing else tr("corpus.play"))

    def _on_tab_changed(self, index: int) -> None:
        if index == FORMS_TAB and self.scope_combo.currentData() == SCOPE_CURRENT:
            self.refresh_forms()
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_hit = self.current_hit() is not None
        self.play_button.setEnabled(has_hit or self.player.is_playing)
        self.go_button.setEnabled(has_hit)
        has_projects = bool(self.projects)
        for button in (
            self.export_csv_button,
            self.export_xlsx_button,
            self.export_tei_button,
        ):
            button.setEnabled(has_projects)
        self.refresh_button.setEnabled(self.folder is not None)

    def hideEvent(self, event: QHideEvent) -> None:
        self.player.pause()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.player.pause()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Zwalnia nagranie odtwarzacza okna (przy zamykaniu programu)."""
        self.player.stop_and_unload()
