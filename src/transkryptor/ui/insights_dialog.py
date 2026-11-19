"""Okno „Wnioski z poprawek szkicu” (zgłoszenie #74).

Po lewej lista rodzajów wniosków (z liczbą pozycji), po prawej strona
wybranego: podsumowanie, reguły zapisu (``ui/insights_rules_page.py``), słowa
poprawiane w całości, wstawki, interpunkcja i wielka litera, mówcy
(``ui/insights_pages.py``). Nad nimi opis porównania - z którym szkicem
(zapisanym po wstawieniu albo odtworzonym z wyniku ASR) i ile słów poprawiono.
Okno nie jest modalne: z wniosku można przejść do miejsca w tekście. Raport
zapisuje się do CSV albo XLSX (materiał dla zespołu). Dane i akcje należą do
``ui/insights_controller.py``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.catalog import CSV_SUFFIX, XLSX_SUFFIX, Table
from transkryptor.i18n import tr
from transkryptor.notation.draft_insights import DraftInsights
from transkryptor.ui.insights_common import change_text, context
from transkryptor.ui.insights_pages import (
    FillersPage,
    PunctuationPage,
    SpeakersPage,
    SummaryPage,
    WordsPage,
)
from transkryptor.ui.insights_rules_page import RulesPage
from transkryptor.ui.theme import set_props

SUMMARY, RULES, WORDS, FILLERS, PUNCTUATION, SPEAKERS = range(6)
PAGE_KEYS = ("summary", "rules", "words", "fillers", "punctuation", "speakers")


def insights_table(insights: DraftInsights, text: str) -> Table:
    """Raport do zapisu: rodzaj wniosku, pozycja, liczba i szczegóły."""
    rows: list[tuple[str | int, ...]] = []
    kind = {key: tr(f"insights.page.{key}") for key in PAGE_KEYS}
    for rule in insights.rules:
        candidate = rule.candidate
        rows.append(
            (
                kind["rules"],
                change_text(candidate.change),
                candidate.count,
                f"{candidate.rule.pattern} → {candidate.rule.replacement}; {candidate.example}",
            )
        )
    for word in insights.words:
        rows.append(
            (kind["words"], f"{word.original} → {word.corrected}", word.count, "")
        )
    for added in insights.added:
        rows.append(
            (
                kind["fillers"],
                f"+ {added.corrected}",
                added.count,
                context(text, added.positions[0]),
            )
        )
    for removed in insights.removed:
        rows.append((kind["fillers"], f"- {removed.original}", removed.count, ""))
    punctuation = insights.punctuation
    for name, value in (
        ("commas", punctuation.commas_removed),
        ("periods", punctuation.periods_removed),
        ("lowercased", punctuation.lowercased),
        ("abbreviations", punctuation.abbreviations),
    ):
        if value:
            rows.append((kind["punctuation"], tr(f"insights.report.{name}"), value, ""))
    for edit in insights.speakers:
        rows.append(
            (
                kind["speakers"],
                f"{edit.before or '-'} → {edit.after or '-'}",
                1,
                " ".join(edit.text.split()),
            )
        )
    header = tuple(
        tr(f"insights.report.column.{name}")
        for name in ("kind", "item", "count", "details")
    )
    return Table(header, tuple(rows))


class InsightsDialog(QDialog):
    """Wnioski z poprawek jednej transkrypcji."""

    refresh_requested = Signal()
    export_requested = Signal(str)
    corpus_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("insights_dialog")
        self.setWindowTitle(tr("insights.title"))
        self.setModal(False)
        self.resize(1080, 700)
        self.rules = RulesPage()
        self.words = WordsPage()
        self.fillers = FillersPage()
        self.punctuation = PunctuationPage()
        self.speakers = SpeakersPage()
        self.summary = SummaryPage(
            [tr(f"insights.page.{key}") for key in PAGE_KEYS[1:]]
        )
        self._build_layout()
        self.summary.open_requested.connect(self.show_page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

    def _build_layout(self) -> None:
        title = QLabel(tr("insights.header"))
        set_props(title, role="title")
        self.description = QLabel()
        self.description.setWordWrap(True)
        set_props(self.description, role="muted")
        self.estimate_label = QLabel(tr("insights.estimated"))
        self.estimate_label.setWordWrap(True)
        set_props(self.estimate_label, role="status", tone="warning")
        refresh = QPushButton(tr("insights.refresh"))
        refresh.clicked.connect(self.refresh_requested)
        self.export_button = QToolButton()
        self.export_button.setText(tr("insights.export"))
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.export_button)
        menu.addAction(
            tr("corpus.export.csv"), lambda: self.export_requested.emit(CSV_SUFFIX)
        )
        menu.addAction(
            tr("corpus.export.xlsx"), lambda: self.export_requested.emit(XLSX_SUFFIX)
        )
        self.export_button.setMenu(menu)
        header = QHBoxLayout()
        column = QVBoxLayout()
        column.addWidget(title)
        column.addWidget(self.description)
        header.addLayout(column, stretch=1)
        header.addWidget(refresh)
        header.addWidget(self.export_button)

        self.nav = QListWidget()
        self.nav.setObjectName("insights_nav")
        self.nav.setMaximumWidth(260)
        self.pages = QStackedWidget()
        for page in (
            self.summary,
            self.rules,
            self.words,
            self.fillers,
            self.punctuation,
            self.speakers,
        ):
            self.pages.addWidget(page)
        for key in PAGE_KEYS:
            self.nav.addItem(tr(f"insights.page.{key}"))
        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.pages, stretch=1)

        self.corpus_button = QPushButton(tr("insights.corpus"))
        self.corpus_button.setObjectName("insights_corpus_button")
        self.corpus_button.clicked.connect(self.corpus_requested)
        close = QPushButton(tr("corpus.close"))
        close.clicked.connect(self.close)
        self.footer = QLabel()
        set_props(self.footer, role="muted")
        footer = QHBoxLayout()
        footer.addWidget(self.footer, stretch=1)
        footer.addWidget(self.corpus_button)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.estimate_label)
        layout.addLayout(body, stretch=1)
        layout.addLayout(footer)

    def show_page(self, page: int) -> None:
        self.nav.setCurrentRow(page)

    def set_empty(self, reason: str) -> None:
        """Brak szkicu do porównania - opis zamiast wniosków."""
        self.description.setText(reason)
        self.estimate_label.hide()
        self.export_button.setEnabled(False)
        self.pages.setEnabled(False)
        self.nav.setEnabled(False)

    def set_insights(
        self,
        insights: DraftInsights,
        text: str,
        *,
        estimated: bool,
        known: Collection[str],
        labels: Mapping[str, str],
        suggested: Collection[str],
        dismissed: int,
    ) -> None:
        """Nowe wnioski (``suggested`` - ustawienia zapisu szkicu do włączenia)."""
        edits = insights.edits
        self.pages.setEnabled(True)
        self.nav.setEnabled(True)
        self.export_button.setEnabled(True)
        self.description.setText(
            tr(
                "insights.description",
                words=edits.draft_words,
                corrected=edits.corrected_words,
            )
        )
        self.estimate_label.setVisible(estimated)
        open_rules = [rule for rule in insights.rules if not rule.dismissed]
        counts = (
            len(open_rules),
            len(insights.words),
            len(edits.added) + len(edits.removed),
            len([name for name in suggested if name != "verbatim"]),
            len(insights.speakers),
        )
        for index, (key, count) in enumerate(
            zip(PAGE_KEYS[1:], counts, strict=True), start=1
        ):
            item = self.nav.item(index)
            if item is not None:
                item.setText(f"{tr(f'insights.page.{key}')} ({count})")
        self.rules.set_rules(insights.rules, text, insights.hidden_rules)
        self.words.set_words(insights.words, known)
        self.fillers.set_fillers(
            insights.added,
            insights.removed,
            text,
            len(edits.added),
            "verbatim" in suggested,
        )
        self.punctuation.set_punctuation(insights.punctuation, suggested)
        self.speakers.set_speakers(insights.speakers, labels, estimated)
        self.summary.set_texts(self._summary_texts(insights, counts, suggested))
        self.footer.setText(tr("insights.footer", dismissed=dismissed))
        if self.nav.currentRow() < 0:
            self.nav.setCurrentRow(SUMMARY)

    @staticmethod
    def _summary_texts(
        insights: DraftInsights, counts: tuple[int, ...], suggested: Collection[str]
    ) -> list[str]:
        rules = [rule for rule in insights.rules if not rule.dismissed]
        texts = [
            (
                tr(
                    "insights.summary.rules",
                    count=counts[0],
                    change=change_text(rules[0].candidate.change),
                )
                if rules
                else tr("insights.summary.rules.none")
            ),
            tr("insights.summary.words", count=counts[1]),
            tr("insights.summary.fillers", count=counts[2]),
            tr("insights.summary.punctuation", count=counts[3]),
            tr("insights.summary.speakers", count=counts[4]),
        ]
        return texts
