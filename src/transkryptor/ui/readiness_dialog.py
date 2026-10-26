"""Okno „Gotowość do oddania”: raport przed eksportem w jednym miejscu.

Raport liczy ``document/readiness.py``; okno grupuje pozycje według
kategorii (z liczbą przy każdej) i po dwukliku albo Enter zamyka się
i przechodzi do miejsca w tekście lub do pola metryczki. Przed eksportem
okno ma przyciski „Eksportuj mimo to” i „Anuluj”; pole „Sprawdzaj przed
eksportem” wyłącza pokazywanie raportu przy eksporcie (ręcznie można go
otworzyć zawsze). ``ReadinessController`` zbiera dane z kontrolerów okna.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.document.readiness import (
    CATEGORIES,
    METADATA,
    Issue,
    ReadinessReport,
)
from transkryptor.i18n import tr
from transkryptor.ui.compare_panel import short
from transkryptor.ui.theme import set_props, tokens

_ROLE = Qt.ItemDataRole.UserRole

# Kod wyniku okna: użytkownik wybrał pozycję raportu (``chosen``).
GO_TO = 2


class ReadinessDialog(QDialog):
    """Pozycje raportu pogrupowane według kategorii."""

    def __init__(
        self,
        report: ReadinessReport,
        check_before_export: bool,
        before_export: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("readiness_dialog")
        self.setWindowTitle(tr("readiness.title"))
        self.chosen: Issue | None = None

        header = QLabel(tr("readiness.header"))
        set_props(header, role="title")
        count = len(report.issues)
        self.summary = QLabel(
            tr("readiness.summary.ready")
            if report.is_ready
            else tr("readiness.summary", count=count)
        )
        self.summary.setWordWrap(True)
        set_props(self.summary, role="muted")

        self.tree = QTreeWidget()
        self.tree.setObjectName("readiness_tree")
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        set_props(self.tree, flat=True)
        self.tree.itemActivated.connect(self._on_activated)
        t = tokens()
        for category in CATEGORIES:
            issues = report.of(category)
            top = QTreeWidgetItem(
                [tr(f"readiness.category.{category}", count=len(issues))]
            )
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if not issues:
                top.setForeground(0, QColor(t.text_muted))
            for issue in issues:
                child = QTreeWidgetItem([self._label(issue)])
                child.setData(0, _ROLE, issue)
                child.setToolTip(0, tr("readiness.item.tooltip"))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(bool(issues))

        self.check_box = QCheckBox(tr("readiness.check_before_export"))
        self.check_box.setChecked(check_before_export)

        if before_export:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
            self.export_button = buttons.addButton(
                tr("readiness.export_anyway"), QDialogButtonBox.ButtonRole.AcceptRole
            )
            buttons.accepted.connect(self.accept)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree, stretch=1)
        layout.addWidget(self.check_box)
        layout.addWidget(buttons)
        self.resize(560, 520)

    @property
    def check_before_export(self) -> bool:
        return self.check_box.isChecked()

    @staticmethod
    def _label(issue: Issue) -> str:
        if issue.category == METADATA:
            return issue.label
        return short(issue.label.strip()) or tr("readiness.item.empty")

    def choose(self, issue: Issue) -> None:
        self.chosen = issue
        self.done(GO_TO)

    def _on_activated(self, item: QTreeWidgetItem) -> None:
        issue = item.data(0, _ROLE)
        if isinstance(issue, Issue):
            self.choose(issue)


class ReadinessController:
    """Raport z bieżącego stanu okna, okno raportu i przejście do pozycji."""

    def __init__(
        self,
        parent: QWidget,
        report: Callable[[], ReadinessReport],
        go_to_range: Callable[[int, int], None],
        go_to_field: Callable[[str], object],
        check_before_export: Callable[[], bool],
        set_check_before_export: Callable[[bool], None],
    ) -> None:
        self._parent = parent
        self._report = report
        self._go_to_range = go_to_range
        self._go_to_field = go_to_field
        self._check = check_before_export
        self._set_check = set_check_before_export
        # Tworzenie okna; testy podstawiają atrapę z gotowym wynikiem.
        self.run: Callable[[ReadinessDialog], int] = lambda dialog: dialog.exec()

    def show(self) -> None:
        """Raport na żądanie (menu eksportu)."""
        self._exec(before_export=False)

    def confirm_export(self) -> bool:
        """True - można eksportować (raport pusty, wyłączony albo „mimo to”)."""
        if not self._check():
            return True
        return self._exec(before_export=True)

    def _exec(self, before_export: bool) -> bool:
        report = self._report()
        if before_export and report.is_ready:
            return True
        dialog = ReadinessDialog(report, self._check(), before_export, self._parent)
        result = self.run(dialog)
        if dialog.check_before_export != self._check():
            self._set_check(dialog.check_before_export)
        issue = dialog.chosen if result == GO_TO else None
        if issue is not None:
            if issue.category == METADATA:
                self._go_to_field(issue.field)
            else:
                self._go_to_range(issue.start, issue.end)
            return False
        return result == QDialog.DialogCode.Accepted
