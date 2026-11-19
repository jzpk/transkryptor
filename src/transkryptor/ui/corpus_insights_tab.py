"""Zakładka „Wnioski” okna korpusu: uczenie z poprawek całego folderu (#74).

„Analizuj korpus” porównuje w tle szkic każdego projektu folderu z jego
tekstem (szkic zapisany po wstawieniu, a bez niego odtworzony z wyniku ASR -
``ui/draft_estimate.py``); projekty bez szkicu ASR są pomijane. Wyniki
sumuje ``notation/corpus_insights.py``: propozycje reguł z liczbą projektów
(i oznaczeniem tych, które wyszły dopiero z całego korpusu), wymiany słów
i podpowiedzi zapisu szkicu.

Zaznaczone propozycje trafiają prosto do aktywnego profilu notacji (zespół
eksportuje go i dzieli się jednym zestawem reguł), a odrzucone zapisują się
w profilu i nie wracają przy kolejnych analizach. Słowa z korpusu dotyczą
wielu nagrań, więc trafiają do słownika globalnego. Akcje wykonuje
``InsightsController`` przez :class:`CorpusInsightsHost`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from transkryptor.corpus.projects import CorpusProject
from transkryptor.document.diff import Version
from transkryptor.i18n import tr
from transkryptor.notation.corpus_insights import (
    CORPUS_MIN_PROJECTS,
    CORPUS_MIN_REPEATS,
    CorpusInsights,
    CorpusRule,
    ProjectEdits,
    corpus_insights,
)
from transkryptor.notation.draft_insights import extract_edits, suggested_settings
from transkryptor.notation.rules import DismissedKey, PhoneticRule
from transkryptor.settings import AsrSettings
from transkryptor.ui.corpus_table import table_widget
from transkryptor.ui.corpus_task import Progress
from transkryptor.ui.draft_estimate import DraftRecipe, project_baseline
from transkryptor.ui.insights_common import change_text, fill_table
from transkryptor.ui.insights_pages import FillersPage, PunctuationPage, WordsPage
from transkryptor.ui.theme import set_props

SHOW_ALL, SHOW_NEW, SHOW_DISMISSED = "all", "new", "dismissed"
Runner = Callable[[str, Callable[[Progress], object], Callable[[object], None]], bool]


class ProjectsSource(Protocol):
    """Projekty folderu korpusu (okno korpusu po skanie)."""

    @property
    def projects(self) -> tuple[CorpusProject, ...]: ...


class CorpusInsightsHost(Protocol):
    """Dane i akcje wniosków (``InsightsController``)."""

    def recipe(self) -> DraftRecipe: ...

    def rules(self) -> tuple[PhoneticRule, ...]: ...

    def dismissed(self) -> tuple[DismissedKey, ...]: ...

    def settings(self) -> AsrSettings: ...

    def profile_name(self) -> str: ...

    def set_dismissed(self, key: DismissedKey, dismissed: bool) -> bool: ...

    def add_rules(self, rules: Sequence[PhoneticRule]) -> bool: ...

    def add_global_words(self, words: Sequence[str]) -> None: ...

    def enable_setting(self, name: str) -> None: ...


def project_edits(
    projects: Sequence[CorpusProject], recipe: DraftRecipe, progress: Progress
) -> list[ProjectEdits]:
    """Różnice szkicu i tekstu projektów, które mają szkic ASR."""
    found = []
    for index, project in enumerate(projects):
        if not progress(index, len(projects)):
            break
        state = project.state
        baseline, estimated = project_baseline(state, recipe)
        if baseline is None:
            continue
        current = Version(
            state.text, state.superscript_ranges, state.paragraph_speakers
        )
        edits = extract_edits(baseline, current, speakers=not estimated)
        found.append(ProjectEdits(project.name, edits, estimated))
    return found


class CorpusInsightsTab(QWidget):
    """Wnioski z poprawek wszystkich projektów folderu."""

    def __init__(
        self,
        host: CorpusInsightsHost | None,
        source: ProjectsSource,
        run: Runner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._source = source
        self._run = run
        self._edits: list[ProjectEdits] | None = None
        self._result: CorpusInsights | None = None
        self._shown: list[CorpusRule] = []
        self._build_layout()
        self._connect_signals()
        self.invalidate()

    def _build_layout(self) -> None:
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        set_props(self.summary_label, role="status", tone="accent")
        self.analyse_button = QPushButton(tr("corpus.insights.analyse"))
        self.analyse_button.setObjectName("corpus_insights_analyse")
        top = QHBoxLayout()
        top.addWidget(self.summary_label, stretch=1)
        top.addWidget(self.analyse_button)
        self.nav = QListWidget()
        self.nav.setMaximumWidth(240)
        for key in ("rules", "words", "settings"):
            self.nav.addItem(tr(f"corpus.insights.page.{key}"))
        self.words = WordsPage(project_vocabulary=False)
        self.fillers = FillersPage()
        self.punctuation = PunctuationPage()
        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.addWidget(self.fillers, stretch=1)
        settings_layout.addWidget(self.punctuation)
        self.pages = QStackedWidget()
        for page in (self._build_rules_page(), self.words, settings_page):
            self.pages.addWidget(page)
        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.pages, stretch=1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(body, stretch=1)
        self.nav.setCurrentRow(0)

    def _build_rules_page(self) -> QWidget:
        self.filter_combo = QComboBox()
        for key in (SHOW_ALL, SHOW_NEW, SHOW_DISMISSED):
            self.filter_combo.addItem(tr(f"corpus.insights.show.{key}"), key)
        self.repeats_spin = QSpinBox()
        self.repeats_spin.setRange(2, 100)
        self.repeats_spin.setValue(CORPUS_MIN_REPEATS)
        self.projects_spin = QSpinBox()
        self.projects_spin.setRange(1, 100)
        self.projects_spin.setValue(CORPUS_MIN_PROJECTS)
        options = QHBoxLayout()
        for caption, widget in (
            ("corpus.insights.show", self.filter_combo),
            ("corpus.insights.min_repeats", self.repeats_spin),
            ("corpus.insights.min_projects", self.projects_spin),
        ):
            label = QLabel(tr(caption))
            label.setBuddy(widget)
            options.addWidget(label)
            options.addWidget(widget)
        options.addStretch(1)
        self.rules_table = table_widget(
            [
                tr(f"corpus.insights.column.{name}")
                for name in ("change", "count", "projects", "example", "state")
            ]
        )
        self.rules_table.setObjectName("corpus_insights_rules")
        self.dismiss_button = QPushButton(tr("insights.rules.dismiss"))
        self.add_button = QPushButton()
        self.add_button.setObjectName("corpus_insights_add_rules")
        self.profile_label = QLabel()
        set_props(self.profile_label, role="muted")
        self.profile_label.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.profile_label, stretch=1)
        buttons.addWidget(self.dismiss_button)
        buttons.addWidget(self.add_button)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addLayout(options)
        layout.addWidget(self.rules_table, stretch=1)
        layout.addLayout(buttons)
        return page

    def _connect_signals(self) -> None:
        self.analyse_button.clicked.connect(self.analyse)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.filter_combo.currentIndexChanged.connect(lambda _index: self._show_rules())
        self.repeats_spin.valueChanged.connect(lambda _value: self._recount())
        self.projects_spin.valueChanged.connect(lambda _value: self._recount())
        self.rules_table.itemChanged.connect(lambda _item: self._update_buttons())
        self.rules_table.itemSelectionChanged.connect(self._update_buttons)
        self.dismiss_button.clicked.connect(self._toggle_dismissed)
        self.add_button.clicked.connect(self.add_checked)
        if self._host is not None:
            host = self._host
            self.words.add_requested.connect(
                lambda words, _global: self._add_words(words)
            )
            self.fillers.setting_requested.connect(
                lambda name: self._enable(host, name)
            )
            self.punctuation.setting_requested.connect(
                lambda name: self._enable(host, name)
            )

    # --- analiza -------------------------------------------------------------------

    def invalidate(self) -> None:
        """Folder się zmienił - wyniki trzeba policzyć od nowa."""
        self._edits, self._result = None, None
        self.summary_label.setText(
            tr("corpus.insights.hint")
            if self._host is not None
            else tr("corpus.insights.unavailable")
        )
        self.analyse_button.setEnabled(self._host is not None)
        self._show_rules()

    def analyse(self) -> bool:
        """Liczy różnice projektów w tle (False - inna praca albo brak projektów)."""
        host, projects = self._host, self._source.projects
        if host is None or not projects:
            self.summary_label.setText(tr("corpus.folder.needed"))
            return False
        recipe = host.recipe()
        return self._run(
            tr("corpus.insights.busy"),
            lambda progress: project_edits(projects, recipe, progress),
            self._apply,
        )

    def _apply(self, edits: object) -> None:
        self._edits = list(edits) if isinstance(edits, list) else []
        self._recount()

    def _recount(self) -> None:
        host = self._host
        if host is None or self._edits is None:
            return
        result = self._result = corpus_insights(
            self._edits,
            host.rules(),
            host.dismissed(),
            self.repeats_spin.value(),
            self.projects_spin.value(),
        )
        self.summary_label.setText(
            tr(
                "corpus.insights.summary",
                projects=result.projects,
                total=len(self._source.projects),
                estimated=result.estimated,
                words=result.draft_words,
                corrected=result.corrected_words,
            )
        )
        settings = host.settings()
        suggested = suggested_settings(
            result.added_count,
            result.punctuation,
            verbatim=settings.verbatim,
            plain=settings.lowercase_plain,
            expand=settings.expand_abbreviations,
        )
        self.words.set_words(result.words, settings.vocabulary_words)
        self.fillers.set_fillers(
            result.added, (), "", result.added_count, "verbatim" in suggested
        )
        self.punctuation.set_punctuation(result.punctuation, suggested)
        self._show_rules()

    # --- propozycje reguł ------------------------------------------------------------

    def _show_rules(self) -> None:
        rules = self._result.rules if self._result is not None else ()
        wanted = self.filter_combo.currentData()
        self._shown = [
            rule
            for rule in rules
            if wanted == SHOW_ALL or (rule.dismissed == (wanted == SHOW_DISMISSED))
        ]
        self.rules_table.blockSignals(True)
        fill_table(
            self.rules_table,
            [
                (
                    change_text(rule.candidate.change),
                    rule.candidate.count,
                    rule.projects,
                    rule.candidate.example,
                    self._state(rule),
                )
                for rule in self._shown
            ],
        )
        for row, rule in enumerate(self._shown):
            item = self.rules_table.item(row, 0)
            if item is not None and not rule.dismissed:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if not rule.corpus_only
                    else Qt.CheckState.Unchecked
                )
        self.rules_table.blockSignals(False)
        name = self._host.profile_name() if self._host is not None else ""
        self.profile_label.setText(tr("corpus.insights.profile", name=name))
        self._update_buttons()

    @staticmethod
    def _state(rule: CorpusRule) -> str:
        state = tr(
            "insights.state.dismissed" if rule.dismissed else "insights.state.new"
        )
        return (
            f"{state}, {tr('corpus.insights.corpus_only')}"
            if rule.corpus_only
            else state
        )

    @property
    def shown_rules(self) -> list[CorpusRule]:
        """Propozycje w tabeli (po filtrze), w kolejności wierszy."""
        return list(self._shown)

    def checked_rules(self) -> list[CorpusRule]:
        found = []
        for row, rule in enumerate(self._shown):
            item = self.rules_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                found.append(rule)
        return found

    def set_checked(self, row: int, checked: bool) -> None:
        item = self.rules_table.item(row, 0)
        if isinstance(item, QTableWidgetItem):
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def _update_buttons(self) -> None:
        count = len(self.checked_rules())
        self.add_button.setText(tr("corpus.insights.add", count=count))
        self.add_button.setEnabled(bool(count) and self._host is not None)
        row = self.rules_table.currentRow()
        selected = self._shown[row] if 0 <= row < len(self._shown) else None
        self.dismiss_button.setEnabled(selected is not None)
        self.dismiss_button.setText(
            tr(
                "insights.rules.restore"
                if selected and selected.dismissed
                else "insights.rules.dismiss"
            )
        )

    def _toggle_dismissed(self) -> None:
        row = self.rules_table.currentRow()
        if self._host is None or not 0 <= row < len(self._shown):
            return
        rule = self._shown[row]
        if self._host.set_dismissed(rule.candidate.change.key, not rule.dismissed):
            self._recount()

    def add_checked(self) -> bool:
        """Zaznaczone propozycje do aktywnego profilu notacji."""
        chosen = self.checked_rules()
        if self._host is None or not chosen:
            return False
        if not self._host.add_rules([rule.candidate.rule for rule in chosen]):
            return False
        self._recount()
        return True

    def _add_words(self, words: list[str]) -> None:
        if self._host is not None:
            self._host.add_global_words(words)
            self._recount()

    def _enable(self, host: CorpusInsightsHost, name: str) -> None:
        host.enable_setting(name)
        self._recount()
