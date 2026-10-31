"""Reguły fonetyczne i przegląd propozycji w panelu szkicu ASR.

Krok „Reguły” to lista reguł z pewnością; zaznaczone stosuje automatycznie
główne okno (REQ-15). Lista przeglądu pokazuje zmiany zastosowane
automatycznie i pozostałe propozycje (REQ-16); wybór i zastosowanie
pozycji sekcja zgłasza sygnałami, a tekst zmienia ``ReviewController``.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.notation.suggestions import (
    RuleInfo,
    Suggestion,
    default_rules,
    rule_infos,
)
from transkryptor.ui import icons
from transkryptor.ui.asr_widgets import section_label, step
from transkryptor.ui.theme import set_props, tokens

APPLIED_MARK = "✓"
PENDING_MARK = "○"

# Indeks górny w etykietach listy (lista nie obsługuje rich text).
_SUPERSCRIPT_LETTERS = str.maketrans("mnu", "ᵐⁿᵘ")


class ReviewSection(QObject):
    """Wybór reguł stosowanych automatycznie i lista przeglądu propozycji."""

    review_item_activated = Signal(int)  # indeks pozycji listy przeglądu
    review_item_apply_requested = Signal(int)
    review_finish_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._review_applied: list[bool] = []
        self.rule_checkboxes: dict[str, QCheckBox] = {}
        self._rules_layout = QVBoxLayout()
        self._rules_layout.setSpacing(2)

        # Reguły są zwinięte do podsumowania: rozwinięte wypychały listę
        # przeglądu poza ekran na typowej wysokości okna.
        self.rules_toggle = QToolButton()
        self.rules_toggle.setObjectName("rules_toggle")
        self.rules_toggle.setCheckable(True)
        self.rules_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.rules_toggle.setArrowType(Qt.ArrowType.RightArrow)
        rules_hint = QLabel(tr("asr.rules.hint"))
        rules_hint.setWordWrap(True)
        set_props(rules_hint, role="muted")
        self.rules_details = QWidget()
        details_layout = QVBoxLayout(self.rules_details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)
        details_layout.addWidget(rules_hint)
        details_layout.addLayout(self._rules_layout)
        self.rules_details.setVisible(False)

        self.suggestions_list = QListWidget()
        self.suggestions_list.setObjectName("asr_review_list")
        self.suggestions_list.setToolTip(
            tr("asr.review.tooltip", applied=APPLIED_MARK, pending=PENDING_MARK)
        )
        self.suggestions_list.setMinimumHeight(130)
        self.suggestions_list.setWordWrap(True)
        self.suggestions_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.apply_suggestion_button = QPushButton(tr("asr.review.apply"))
        icons.set_icon(self.apply_suggestion_button, "check", "text", "text_muted")
        self.apply_suggestion_button.setEnabled(False)
        self.finish_review_button = QPushButton(tr("asr.review.finish"))
        set_props(self.finish_review_button, variant="ghost")
        self.finish_review_button.setToolTip(tr("asr.review.finish.tooltip"))
        self.finish_review_button.setEnabled(False)

        self.rules_toggle.toggled.connect(self._on_rules_toggled)
        self.suggestions_list.currentRowChanged.connect(self._on_review_row_changed)
        self.suggestions_list.itemClicked.connect(self._on_review_item_clicked)
        self.suggestions_list.itemDoubleClicked.connect(
            self._on_review_item_double_clicked
        )
        self.apply_suggestion_button.clicked.connect(self._on_apply_clicked)
        self.finish_review_button.clicked.connect(self.review_finish_requested.emit)
        self.set_rules(rule_infos(default_rules()))

    def build_rules_step(self) -> QWidget:
        """Krok 2 panelu: podsumowanie reguł, po rozwinięciu - lista."""
        return step("2", tr("asr.step.rules"), [self.rules_toggle, self.rules_details])

    def build_review_box(self) -> QVBoxLayout:
        """Lista przeglądu z przyciskami pod listą segmentów."""
        review_row = QHBoxLayout()
        review_row.addWidget(self.apply_suggestion_button)
        review_row.addStretch(1)
        review_row.addWidget(self.finish_review_button)
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(section_label(tr("asr.review")))
        box.addWidget(self.suggestions_list, stretch=1)
        box.addLayout(review_row)
        return box

    # --- reguły --------------------------------------------------------------

    def set_rules(self, rules: tuple[RuleInfo, ...]) -> None:
        """Lista reguł z pewnością; zaznaczenie istniejących reguł zostaje.

        Nowa reguła jest zaznaczona według ``auto_apply`` z definicji.
        """
        previous = self.selected_rule_codes()
        known = set(self.rule_checkboxes)
        for checkbox in self.rule_checkboxes.values():
            self._rules_layout.removeWidget(checkbox)
            checkbox.deleteLater()
        self.rule_checkboxes = {}
        for rule in rules:
            checkbox = QCheckBox(_rule_text(rule.label, rule.confidence))
            checkbox.setChecked(
                rule.code in previous if rule.code in known else rule.auto_apply
            )
            checkbox.setToolTip(tr("asr.rule.tooltip"))
            checkbox.toggled.connect(self._update_rules_summary)
            self._rules_layout.addWidget(checkbox)
            self.rule_checkboxes[rule.code] = checkbox
        self._update_rules_summary()

    def selected_rule_codes(self) -> frozenset[str]:
        """Kody reguł zaznaczonych do automatycznego stosowania (REQ-15)."""
        return frozenset(
            code for code, box in self.rule_checkboxes.items() if box.isChecked()
        )

    def _on_rules_toggled(self, expanded: bool) -> None:
        self.rules_details.setVisible(expanded)
        self.rules_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._update_rules_summary()

    def _update_rules_summary(self) -> None:
        enabled = len(self.selected_rule_codes())
        action = (
            tr("asr.rules.collapse")
            if self.rules_toggle.isChecked()
            else tr("asr.rules.change")
        )
        self.rules_toggle.setText(
            tr(
                "asr.rules.summary",
                enabled=enabled,
                total=len(self.rule_checkboxes),
                action=action,
            )
        )

    # --- przegląd ------------------------------------------------------------

    def set_review_items(self, items: list[tuple[Suggestion, bool]]) -> None:
        """Pokazuje zmiany zastosowane automatycznie i pozostałe propozycje.

        ``items`` to pary (propozycja, czy zastosowana) w kolejności tekstu.
        """
        self._review_applied = [applied for _suggestion, applied in items]
        self.suggestions_list.clear()
        if not items:
            item = QListWidgetItem(tr("asr.review.empty"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.suggestions_list.addItem(item)
        for suggestion, applied in items:
            item = QListWidgetItem(_review_label(suggestion, applied))
            item.setToolTip(suggestion.message)
            if applied:
                item.setForeground(QColor(tokens().success))
            self.suggestions_list.addItem(item)
        self.finish_review_button.setEnabled(bool(items))
        self._on_review_row_changed(self.suggestions_list.currentRow())

    def clear_review(self) -> None:
        self._review_applied = []
        self.suggestions_list.clear()
        self.finish_review_button.setEnabled(False)
        self.apply_suggestion_button.setEnabled(False)

    def _pending(self, index: int) -> bool:
        return (
            0 <= index < len(self._review_applied) and not self._review_applied[index]
        )

    def _on_review_row_changed(self, row: int) -> None:
        self.apply_suggestion_button.setEnabled(self._pending(row))

    def _on_review_item_clicked(self, item: QListWidgetItem) -> None:
        index = self.suggestions_list.row(item)
        if 0 <= index < len(self._review_applied):
            self.review_item_activated.emit(index)

    def _on_review_item_double_clicked(self, item: QListWidgetItem) -> None:
        index = self.suggestions_list.row(item)
        if self._pending(index):
            self.review_item_apply_requested.emit(index)

    def _on_apply_clicked(self) -> None:
        index = self.suggestions_list.currentRow()
        if self._pending(index):
            self.review_item_apply_requested.emit(index)


def _rule_text(label: str, confidence: float) -> str:
    """Dwie linie: reguła, potem przykład i pewność - mieszczą się w panelu."""
    rule, has_example, example = label.partition(" (")
    detail = f"{example.removesuffix(')')} · " if has_example else ""
    return f"{rule}\n{detail}{tr('asr.confidence', confidence=f'{confidence:.0%}')}"


def _review_label(suggestion: Suggestion, applied: bool) -> str:
    """Np. „✓ robią → robioᵐ (Nosowość, 50%)” - słowo przed i po zmianie."""
    replacement = list(suggestion.replacement)
    for start, end in suggestion.superscript_ranges:
        for i in range(start, end):
            replacement[i] = replacement[i].translate(_SUPERSCRIPT_LETTERS)
    before = suggestion.word or suggestion.original
    offset = suggestion.start - suggestion.word_start if suggestion.word else 0
    after = (
        before[:offset]
        + "".join(replacement)
        + before[offset + len(suggestion.original) :]
    )
    mark = APPLIED_MARK if applied else PENDING_MARK
    category = suggestion.message.split(":")[0]
    return f"{mark} {before} → {after} ({category}, {suggestion.confidence:.0%})"
