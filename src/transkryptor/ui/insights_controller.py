"""Polecenie „Wnioski z poprawek szkicu…” i jego akcje (zgłoszenie #74).

Wnioski liczy ``notation/draft_insights.py`` z porównania szkicu po
wstawieniu (zapisanego w projekcie - ``ReviewController.baseline``; bez niego
odtworzonego z wyniku ASR, ``ui/draft_estimate.py``) z tekstem edytora.
Polecenie jest w menu „Otwórz” zaraz za „Porównaj z…” (w wąskim oknie - w menu
„Więcej poleceń”), a przycisk propozycji reguły w pasku stanu ma pozycję
„Wszystkie propozycje…”, która otwiera okno na regułach.

Akcje wniosków używają istniejących mechanizmów: reguła powstaje w edytorze
reguł (Ustawienia, zakładka reguł), odrzucenie zapisuje plik reguł
użytkownika (a więc profil notacji), słowa trafiają do słownika ASR projektu
albo globalnego, a podpowiedziane ustawienia zapisu szkicu - do bieżącego
profilu. Kontroler podaje też te dane zakładce „Wnioski” okna korpusu
(``ui/corpus_insights_tab.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from transkryptor.document.diff import Version
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.draft_insights import (
    DraftInsights,
    draft_insights,
    suggested_settings,
)
from transkryptor.notation.learning import MIN_REPEATS
from transkryptor.notation.rules import DismissedKey, PhoneticRule
from transkryptor.settings import AsrSettings, split_vocabulary
from transkryptor.ui.draft_estimate import DraftRecipe, estimated_baseline
from transkryptor.ui.draft_styler import DraftStyler
from transkryptor.ui.insights_dialog import (
    RULES,
    SUMMARY,
    InsightsDialog,
    insights_table,
)
from transkryptor.ui.messages import show_error
from transkryptor.ui.table_export import export_table

if TYPE_CHECKING:
    from transkryptor.ui.main_window import MainWindow

TEXTS = "insights"


class InsightsController(QObject):
    """Okno wniosków bieżącej transkrypcji i akcje wniosków (także korpusu)."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._styler = DraftStyler(lambda: window.settings_store.current.asr)
        self.min_repeats = MIN_REPEATS
        self.dialog: InsightsDialog | None = None
        self.insights: DraftInsights | None = None
        self.action = QAction(tr("insights.action"), window)
        self.action.setObjectName("insights_action")
        self.action.setToolTip(tr("insights.action.tooltip"))
        self.action.triggered.connect(lambda _checked=False: self.show())
        self.all_action = QAction(tr("insights.all_proposals"), window)
        self.all_action.triggered.connect(lambda _checked=False: self.show(RULES))
        window.main_toolbar.open_menu.add_compare_actions([self.action])
        window.learning.add_menu_action(self.all_action)
        window.corpus.set_insights(self)
        window.rules_store.rules_changed.connect(self.refresh)
        # Pokazanie okna; testy podstawiają atrapę zamiast ``show``.
        self.run = lambda dialog: dialog.show()

    # --- dane (także dla korpusu) --------------------------------------------------

    def settings(self) -> AsrSettings:
        return self._window.settings_store.current.asr

    def recipe(self) -> DraftRecipe:
        """Jak wstawiany jest szkic - do odtworzenia szkicu starszych projektów."""
        current = self._window.settings_store.current
        return DraftRecipe(
            self._styler,
            current.asr,
            current.notation.ellipsis,
            self._window.rules_store.rules,
            self._window.asr_panel.selected_rule_codes(),
        )

    def rules(self) -> tuple[PhoneticRule, ...]:
        return self._window.rules_store.rules

    def dismissed(self) -> tuple[DismissedKey, ...]:
        return self._window.rules_store.dismissed

    def profile_name(self) -> str:
        return self._window.profiles.active

    def baseline(self) -> tuple[Version | None, bool]:
        """Szkic odniesienia i czy jest odtworzony z wyniku ASR."""
        review = self._window.review
        if review.baseline is not None:
            return review.baseline, False
        state = self._window.session.capture_state()
        return estimated_baseline(state, self.recipe()), True

    def compute(self) -> tuple[DraftInsights, Version, bool] | None:
        baseline, estimated = self.baseline()
        if baseline is None:
            return None
        current = self._window.review.current_version()
        insights = draft_insights(
            baseline,
            current,
            self.rules(),
            self.dismissed(),
            self.min_repeats,
            speakers=not estimated,
        )
        return insights, current, estimated

    def known_words(self) -> set[str]:
        _prompt, project = self._window.asr_panel.asr_context()
        return {*project, *self.settings().vocabulary_words}

    # --- okno ----------------------------------------------------------------------

    def show(self, page: int = SUMMARY) -> None:
        if self.dialog is None:
            dialog = self.dialog = InsightsDialog(self._window)
            dialog.refresh_requested.connect(self.refresh)
            dialog.export_requested.connect(self.export)
            dialog.corpus_requested.connect(self.open_corpus)
            dialog.rules.create_requested.connect(self.create_rule)
            dialog.rules.dismiss_requested.connect(self.dismiss_rule)
            dialog.rules.go_to_requested.connect(self.go_to)
            dialog.rules.min_repeats_changed.connect(self._set_min_repeats)
            dialog.words.add_requested.connect(self.add_words)
            dialog.fillers.setting_requested.connect(self.enable_setting)
            dialog.punctuation.setting_requested.connect(self.enable_setting)
            dialog.speakers.go_to_requested.connect(self.go_to)
            self.refresh()
            self.run(dialog)
        else:
            self.refresh()
            self.dialog.raise_()
            self.dialog.activateWindow()
        self.dialog.show_page(page)

    def refresh(self) -> None:
        dialog = self.dialog
        if dialog is None:
            return
        computed = self.compute()
        if computed is None:
            self.insights = None
            dialog.set_empty(tr("insights.no_draft"))
            return
        insights, current, estimated = computed
        self.insights = insights
        settings = self.settings()
        suggested = suggested_settings(
            len(insights.edits.added),
            insights.punctuation,
            verbatim=settings.verbatim,
            plain=settings.lowercase_plain,
            expand=settings.expand_abbreviations,
        )
        speakers = self._window.session.document.speakers
        dialog.set_insights(
            insights,
            current.text,
            estimated=estimated,
            known=self.known_words(),
            labels={s.key: s.label or s.key for s in speakers},
            suggested=suggested,
            dismissed=len(self.dismissed()),
        )

    def _set_min_repeats(self, value: int) -> None:
        self.min_repeats = value
        self.refresh()

    # --- akcje ---------------------------------------------------------------------

    def create_rule(self, row: int) -> None:
        """Edytor reguł z proponowaną regułą (zapis przez Ustawienia)."""
        if self.insights is not None and 0 <= row < len(self.insights.rules):
            self._window.edit_new_rule(self.insights.rules[row].candidate.rule)
            self.refresh()

    def dismiss_rule(self, row: int, dismissed: bool) -> None:
        if self.insights is not None and 0 <= row < len(self.insights.rules):
            self.set_dismissed(self.insights.rules[row].candidate.change.key, dismissed)

    def set_dismissed(self, key: DismissedKey, dismissed: bool) -> bool:
        """Odrzuca propozycję w profilu (albo cofa odrzucenie)."""
        try:
            self._window.rules_store.set_dismissed(key, dismissed)
        except AppError as error:
            show_error(self._window, tr("insights.error.save"), error)
            return False
        return True

    def add_rules(self, rules: Sequence[PhoneticRule]) -> bool:
        """Reguły prosto do profilu (korpus: zaznaczone propozycje)."""
        store = self._window.rules_store
        try:
            store.save_user_rules([*store.user_rules, *rules])
        except AppError as error:
            show_error(self._window, tr("settings.rules.save_error"), error)
            return False
        return True

    def add_words(self, words: list[str], global_vocabulary: bool) -> None:
        """Słowa do słownika ASR projektu albo globalnego (bez powtórzeń)."""
        if global_vocabulary:
            self.add_global_words(words)
        else:
            panel = self._window.asr_panel
            prompt, vocabulary = panel.asr_context()
            added = tuple(dict.fromkeys((*vocabulary, *words)))
            if added != vocabulary:
                panel.set_asr_context(prompt, added)
                self._window.session.asr_context_changed()
        self._window.show_status(tr("insights.words.added", count=len(words)))
        self.refresh()

    def add_global_words(self, words: Sequence[str]) -> None:
        current = self._window.settings_store.current
        known = split_vocabulary(current.asr.vocabulary)
        merged = tuple(dict.fromkeys((*known, *words)))
        if merged != known:
            asr = replace(current.asr, vocabulary="\n".join(merged))
            self._window.profiles.save_settings(replace(current, asr=asr))

    def enable_setting(self, name: str) -> None:
        """Włącza ustawienie zapisu szkicu (pole ``AsrSettings``) w profilu."""
        current = self._window.settings_store.current
        asr = replace(current.asr, **{name: True})  # type: ignore[arg-type]  # pola logiczne AsrSettings
        self._window.profiles.save_settings(replace(current, asr=asr))
        self._window.show_status(tr("insights.setting.enabled"))
        self.refresh()

    def go_to(self, position: int) -> None:
        """Zaznacza słowo w miejscu ``position`` tekstu edytora."""
        editor = self._window.editor
        text = editor.plain_text()
        end = position
        while end < len(text) and not text[end].isspace():
            end += 1
        editor.setTextCursor(editor.track_range(position, end))
        editor.ensureCursorVisible()

    def export(self, suffix: str) -> bool:
        if self.insights is None or self.dialog is None:
            return False
        name = Path(self._window.session.project_name or tr("stats.default_name")).stem
        table = insights_table(self.insights, self._window.editor.plain_text())
        return export_table(
            self.dialog, table, f"{name}{tr('insights.name_suffix')}", suffix, TEXTS
        )

    def open_corpus(self) -> None:
        dialog = self._window.corpus.open_dialog()
        dialog.tabs.setCurrentWidget(dialog.insights)

    def set_locked(self, locked: bool) -> None:
        for action in (self.action, self.all_action):
            action.setEnabled(not locked)
        if self.dialog is not None:
            self.dialog.setEnabled(not locked)
