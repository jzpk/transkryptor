"""Okno „Przegląd serii”: tabela stanu wszystkich nagrań folderu serii.

Stan liczy ``corpus/series_overview.py`` w wątku w tle (``CorpusTask``) -
wczytanie wielu projektów nie blokuje okna. Dwuklik w wierszu (albo Enter)
otwiera nagranie: jego projekt albo nową transkrypcję.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.series_overview import (
    OverviewCancelled,
    ReadinessOptions,
    SeriesOverview,
    SeriesRow,
    series_overview,
)
from transkryptor.document.progress import format_duration, format_percent
from transkryptor.i18n import tr
from transkryptor.ui.corpus_task import CorpusTask, Progress

_SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class _Item(QTableWidgetItem):
    """Komórka sortowana po wartości (``_SORT_ROLE``), nie po tekście."""

    def __init__(self, text: str, key: object) -> None:
        super().__init__(text)
        self.setData(_SORT_ROLE, key)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine, theirs = self.data(_SORT_ROLE), other.data(_SORT_ROLE)
        try:
            return bool(mine < theirs)
        except TypeError:
            return super().__lt__(other)


class SeriesTable(QTableWidget):
    """Nagranie, długość, stan, pokrycie, ostatnia edycja, czas pracy."""

    NAME, DURATION, STATUS, COVERAGE, MODIFIED, WORK = range(6)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 6, parent)
        self.setObjectName("series_overview_table")
        self.setHorizontalHeaderLabels(
            [
                tr("series.overview.column.recording"),
                tr("series.overview.column.duration"),
                tr("series.overview.column.status"),
                tr("series.overview.column.coverage"),
                tr("series.overview.column.modified"),
                tr("series.overview.column.work"),
            ]
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.NAME, QHeaderView.ResizeMode.Stretch)
        # Domyślnie w kolejności serii (Qt bez tego sortuje malejąco).
        header.setSortIndicator(self.NAME, Qt.SortOrder.AscendingOrder)
        self._rows: list[SeriesRow] = []

    def set_rows(self, rows: tuple[SeriesRow, ...]) -> None:
        self._rows = list(rows)
        self.setSortingEnabled(False)
        self.clearContents()
        self.setRowCount(len(self._rows))
        for number, row in enumerate(self._rows):
            for column, item in enumerate(_cells(number, row)):
                self.setItem(number, column, item)
        self.setSortingEnabled(True)

    def recording_at(self, row: int) -> Path | None:
        item = self.item(row, self.NAME)
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        return self._rows[index].recording if isinstance(index, int) else None


def _cells(number: int, row: SeriesRow) -> list[QTableWidgetItem]:
    name = _Item(row.recording.name, number)
    name.setData(Qt.ItemDataRole.UserRole, number)
    name.setToolTip(str(row.project or row.recording))
    duration = row.duration_ms
    status = _Item(tr(f"series.overview.status.{row.status}"), row.status)
    if row.error:
        status.setToolTip(row.error)
    elif row.issues:
        status.setToolTip(tr("series.overview.issues", count=row.issues))
    modified = row.modified
    cells: list[QTableWidgetItem] = [
        name,
        _Item(format_duration(duration // 1000) if duration else "-", duration or 0),
        status,
        _Item(format_percent(row.coverage), row.coverage or 0.0),
        _Item(
            (
                QLocale().toString(QDateTime(modified), QLocale.FormatType.ShortFormat)
                if modified
                else "-"
            ),
            modified.timestamp() if modified else 0.0,
        ),
        _Item(
            format_duration(row.work_seconds) if row.project else "-",
            row.work_seconds,
        ),
    ]
    for item in cells[1:]:
        if item is not status:
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
    return cells


class SeriesOverviewDialog(QDialog):
    """Przegląd serii; ``open_requested(nagranie)`` - dwuklik w wierszu."""

    open_requested = Signal(Path)

    def __init__(
        self,
        folder: Path,
        options: Callable[[], ReadinessOptions],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("series_overview_dialog")
        self.setWindowTitle(tr("series.overview.title", folder=folder.name))
        self.resize(820, 460)
        self.folder = folder
        self._options = options
        self._task: CorpusTask | None = None
        self.overview: SeriesOverview | None = None
        self._build_layout()
        self.refresh()

    def _build_layout(self) -> None:
        self.summary_label = QLabel()
        self.summary_label.setObjectName("series_overview_summary")
        self.summary_label.setWordWrap(True)
        self.table = SeriesTable(self)
        self.table.cellDoubleClicked.connect(lambda row, _c: self._open_row(row))
        self.table.activated.connect(lambda index: self._open_row(index.row()))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        self.refresh_button = QPushButton(tr("series.overview.refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addButton(self.refresh_button, QDialogButtonBox.ButtonRole.ActionRole)
        hint = QLabel(tr("series.overview.hint"))
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    # --- wczytywanie ---------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._task is not None

    def refresh(self) -> None:
        """Wczytuje stan serii od nowa (w tle)."""
        if self._task is not None:
            return
        folder, options = self.folder, self._options()

        def work(progress: Progress) -> SeriesOverview:
            return series_overview(folder, options, progress)

        task = CorpusTask(work, self)
        task.progressed.connect(self._on_progress)
        task.finished.connect(self._finish)
        self._task = task
        self.refresh_button.setEnabled(False)
        self.summary_label.setText(tr("series.overview.loading"))
        task.start()

    def wait(self, timeout_ms: int = 30_000) -> None:
        """Czeka na koniec wczytywania i obsługuje wynik (testy)."""
        task = self._task
        if task is not None and task.wait(timeout_ms):
            QApplication.sendPostedEvents()
            QApplication.processEvents()

    def _on_progress(self, done: int, total: int) -> None:
        self.summary_label.setText(
            tr("series.overview.loading.progress", done=done, total=total)
        )

    def _finish(self) -> None:
        task = self._task
        if task is None:
            return
        self._task = None
        task.deleteLater()
        self.refresh_button.setEnabled(True)
        error = task.error
        if error is not None and not isinstance(error, OverviewCancelled):
            raise error
        result = task.result
        if isinstance(result, SeriesOverview):
            self.overview = result
            self.table.set_rows(result.rows)
            self.summary_label.setText(summary_text(result))

    def _open_row(self, row: int) -> None:
        recording = self.table.recording_at(row)
        if recording is not None:
            self.open_requested.emit(recording)

    def closeEvent(self, event: QCloseEvent) -> None:
        task = self._task
        if task is not None:
            task.cancel()
            task.wait()
            self._finish()
        super().closeEvent(event)


def summary_text(overview: SeriesOverview) -> str:
    """Podsumowanie serii: gotowe, łączna długość i część przetranskrybowana."""
    total = overview.duration_ms
    ratio = overview.covered_ms / total if total else None
    return tr(
        "series.overview.summary",
        ready=overview.ready,
        total=len(overview.rows),
        duration=format_duration(total // 1000),
        covered=format_duration(overview.covered_ms // 1000),
        percent=format_percent(ratio),
    )


__all__ = ["SeriesOverviewDialog", "SeriesTable", "summary_text"]
