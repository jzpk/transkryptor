"""Okno „Statystyki projektu” i podgląd dziennego celu w pasku stanu.

Statystyki liczy ``document/progress.py`` z bieżącego stanu projektu:
część nagrania przetranskrybowana (pokrycie tekstem) i zweryfikowana, czas
aktywnej pracy (``ui/work_time.py``), luki w transkrypcji (jak na mapie
pokrycia fali, ``ui/coverage_controller.py``), tempo i szacowany czas do końca,
liczby słów (także na mówcę), otwartych komentarzy i ostrzeżeń. Tabelę
można zapisać do CSV albo XLSX (jak tabele korpusu). ``ProgressController``
tworzy polecenie okna i - gdy w ustawieniach jest dzienny cel - etykietę
postępu dnia w pasku stanu.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.catalog import CSV_SUFFIX, XLSX_SUFFIX, Table, save_table
from transkryptor.document.progress import ProjectStats, project_stats, stats_rows
from transkryptor.document.project import ProjectState
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props

# Co tyle odświeża się etykieta dziennego celu (pokrycie liczone od nowa,
# więc nie przy każdej sekundzie pracy).
GOAL_REFRESH_MS = 30_000


def stats_table(stats: ProjectStats) -> Table:
    """Statystyki jako tabela do zapisu (nazwa, wartość)."""
    return Table(
        (tr("stats.column.name"), tr("stats.column.value")),
        tuple((name, value) for name, value in stats_rows(stats)),
    )


class StatsDialog(QDialog):
    """Tabela statystyk z zapisem do CSV/XLSX."""

    def __init__(
        self, stats: ProjectStats, default_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stats_dialog")
        self.setWindowTitle(tr("stats.title"))
        self._table = stats_table(stats)
        self._default_name = default_name

        header = QLabel(tr("stats.header"))
        set_props(header, role="title")
        hint = QLabel(tr("stats.hint"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")

        self.table = QTableWidget(len(self._table.rows), 2)
        self.table.setObjectName("stats_table")
        self.table.setHorizontalHeaderLabels(list(self._table.header))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (name, value) in enumerate(self._table.rows):
            self.table.setItem(row, 0, QTableWidgetItem(str(name)))
            self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        columns = self.table.horizontalHeader()
        columns.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        columns.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.csv_button = buttons.addButton(
            tr("stats.export_csv"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.xlsx_button = buttons.addButton(
            tr("stats.export_xlsx"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.csv_button.clicked.connect(lambda: self.export(CSV_SUFFIX))
        self.xlsx_button.clicked.connect(lambda: self.export(XLSX_SUFFIX))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(hint)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(buttons)
        self.resize(480, 520)

    @property
    def rows(self) -> tuple[tuple[object, ...], ...]:
        return self._table.rows

    def export(self, suffix: str) -> bool:
        """Zapis tabeli do CSV albo XLSX; False - anulowano albo błąd."""
        path, _selected = QFileDialog.getSaveFileName(
            self,
            tr("stats.export.dialog"),
            f"{self._default_name}{suffix}",
            tr("stats.export.filter", pattern=f"*{suffix}"),
        )
        if not path:
            return False
        if not path.lower().endswith(suffix):
            path += suffix
        try:
            save_table(self._table, path, tr("stats.title"))
        except AppError as error:
            show_error(self, tr("stats.export.error"), error)
            return False
        return True


class ProgressController(QObject):
    """Polecenie „Statystyki projektu…” i etykieta dziennego celu."""

    def __init__(
        self,
        parent: QWidget,
        state: Callable[[], ProjectState],
        warning_count: Callable[[], int],
        daily_goal_min: Callable[[], int],
        default_name: Callable[[], str],
        silence: Callable[[], Sequence[tuple[int, int]]] = lambda: (),
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._state = state
        self._warning_count = warning_count
        self._goal = daily_goal_min
        self._default_name = default_name
        # Cisza wykryta w nagraniu - luki liczone jak na mapie pokrycia fali.
        self._silence = silence
        self.stats_action = QAction(tr("stats.action"), parent)
        self.stats_action.setToolTip(tr("stats.action.tooltip"))
        self.stats_action.triggered.connect(lambda _checked=False: self.show())
        self.goal_label = QLabel()
        self.goal_label.setObjectName("daily_goal_label")
        set_props(self.goal_label, role="badge")
        self.goal_label.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(GOAL_REFRESH_MS)
        self._timer.timeout.connect(self.refresh_goal)
        self._timer.start()
        # Tworzenie okna; testy podstawiają atrapę zamiast ``exec``.
        self.run: Callable[[StatsDialog], int] = lambda dialog: dialog.exec()

    def stats(self) -> ProjectStats:
        return project_stats(
            self._state(),
            date.today().isoformat(),
            self._warning_count(),
            silence=self._silence(),
        )

    def show(self) -> None:
        dialog = StatsDialog(self.stats(), self._default_name(), self._parent)
        self.run(dialog)

    def refresh_goal(self) -> None:
        """Postęp dnia względem celu (ukryta bez celu w ustawieniach)."""
        goal = self._goal()
        self.goal_label.setVisible(goal > 0)
        if goal <= 0:
            return
        done = self.stats().today_covered_ms // 60000
        self.goal_label.setText(tr("stats.goal", done=done, goal=goal))
        set_props(self.goal_label, role="badge", tone="success" if done >= goal else "")
