"""Strona „Reguły zapisu” okna wniosków z poprawek (zgłoszenie #74).

Wszystkie propozycje reguł z poprawek szkicu naraz (a nie tylko najczęstsza,
jak przycisk w pasku stanu): zmiana, miejsce w słowie, liczba poprawek
i przykład, a przy wybranej - gotowy wzorzec, poprawki w kontekście (z
przejściem do tekstu) i liczba miejsc, które pasują do wzorca, ale nie
zostały poprawione. Strona ogłasza decyzje sygnałami; reguły tworzy
i odrzucenia zapisuje kontroler.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.notation.draft_insights import RuleInsight
from transkryptor.notation.learning import MIN_REPEATS
from transkryptor.ui.corpus_table import table_widget
from transkryptor.ui.insights_common import change_text, context, fill_table, place_name
from transkryptor.ui.theme import set_props

PLACES_SHOWN = 6


class RulesPage(QWidget):
    """Tabela propozycji reguł z panelem szczegółów wybranej."""

    create_requested = Signal(int)
    dismiss_requested = Signal(int, bool)
    go_to_requested = Signal(int)
    min_repeats_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._insights: list[RuleInsight] = []
        self._text = ""
        self._build_layout()
        self.table.itemSelectionChanged.connect(self._show_details)
        self.create_button.clicked.connect(lambda: self._decide(create=True))
        self.dismiss_button.clicked.connect(lambda: self._decide(create=False))
        self.repeats_spin.valueChanged.connect(self.min_repeats_changed)
        self.details.linkActivated.connect(
            lambda link: self.go_to_requested.emit(int(link))
        )

    def _build_layout(self) -> None:
        hint = QLabel(tr("insights.rules.hint"))
        hint.setWordWrap(True)
        set_props(hint, role="muted")
        self.repeats_spin = QSpinBox()
        self.repeats_spin.setRange(2, 20)
        self.repeats_spin.setValue(MIN_REPEATS)
        repeats = QLabel(tr("insights.rules.min_repeats"))
        repeats.setBuddy(self.repeats_spin)
        top = QHBoxLayout()
        top.addWidget(hint, stretch=1)
        top.addWidget(repeats)
        top.addWidget(self.repeats_spin)
        self.table = table_widget(
            [
                tr(f"insights.rules.column.{name}")
                for name in ("change", "place", "count", "example", "state")
            ]
        )
        self.table.setObjectName("insights_rules_table")
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setMinimumWidth(280)
        self.details.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.create_button = QPushButton(tr("learning.create"))
        self.create_button.setObjectName("insights_create_rule")
        self.dismiss_button = QPushButton(tr("insights.rules.dismiss"))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.dismiss_button)
        buttons.addWidget(self.create_button)
        side = QVBoxLayout()
        side.addWidget(self.details, stretch=1)
        side.addLayout(buttons)
        middle = QHBoxLayout()
        middle.addWidget(self.table, stretch=3)
        middle.addLayout(side, stretch=2)
        self.hidden_label = QLabel()
        self.hidden_label.setWordWrap(True)
        set_props(self.hidden_label, role="muted")
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(middle, stretch=1)
        layout.addWidget(self.hidden_label)

    def set_rules(
        self, insights: Sequence[RuleInsight], text: str, hidden: int = 0
    ) -> None:
        """Propozycje do pokazania; ``hidden`` - rzadszych zmian poniżej progu."""
        chosen = self.table.currentRow()
        self._insights, self._text = list(insights), text
        fill_table(
            self.table,
            [
                (
                    change_text(item.candidate.change),
                    place_name(item.candidate.change.place),
                    item.candidate.count,
                    item.candidate.example,
                    tr(
                        "insights.state.dismissed"
                        if item.dismissed
                        else "insights.state.new"
                    ),
                )
                for item in self._insights
            ],
        )
        self.hidden_label.setText(
            tr("insights.rules.hidden", count=hidden) if hidden else ""
        )
        if self._insights:
            self.table.selectRow(min(max(chosen, 0), len(self._insights) - 1))
        self._show_details()

    @property
    def insights(self) -> list[RuleInsight]:
        return list(self._insights)

    def current(self) -> int:
        row = self.table.currentRow()
        return row if 0 <= row < len(self._insights) else -1

    def _show_details(self) -> None:
        row = self.current()
        self.create_button.setEnabled(row >= 0)
        self.dismiss_button.setEnabled(row >= 0)
        if row < 0:
            self.details.setText(tr("insights.rules.empty"))
            return
        item = self._insights[row]
        self.dismiss_button.setText(
            tr("insights.rules.restore" if item.dismissed else "insights.rules.dismiss")
        )
        rule = item.candidate.rule
        lines = [
            f"<b>{escape(change_text(item.candidate.change))}</b> · {escape(rule.code)}",
            escape(
                tr(
                    "insights.rules.pattern",
                    pattern=rule.pattern,
                    replacement=rule.replacement,
                )
            ),
            f"<b>{escape(tr('insights.rules.places', count=len(item.places)))}</b>",
        ]
        for place in item.places[:PLACES_SHOWN]:
            lines.append(
                f'<a href="{place.position}">{escape(context(self._text, place.position))}</a>'
            )
        if item.unmatched:
            lines.append(escape(tr("insights.rules.unmatched", count=item.unmatched)))
        self.details.setText("<br>".join(lines))

    def _decide(self, *, create: bool) -> None:
        row = self.current()
        if row < 0:
            return
        if create:
            self.create_requested.emit(row)
        else:
            self.dismiss_requested.emit(row, not self._insights[row].dismissed)
