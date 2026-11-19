"""Okno „Wnioski z poprawek szkicu” i zakładka „Wnioski” korpusu (zgłoszenie #74)."""

import csv
from pathlib import Path

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog

from transkryptor.asr.results import SegmentResult, TranscriptionResult, WordResult
from transkryptor.document.diff import Version
from transkryptor.document.project import (
    AsrDraft,
    AsrSegment,
    ProjectState,
    save_project,
)
from transkryptor.notation.rules import PhoneticRule
from transkryptor.ui.insights_controller import InsightsController
from transkryptor.ui.insights_dialog import InsightsDialog, insights_table
from transkryptor.ui.main_window import MainWindow

WORDS = ("mleko", "chleb", "ser", "dom", "kartofle", "i", "kartofle")


def draft() -> TranscriptionResult:
    words = tuple(
        WordResult(i * 0.5, i * 0.5 + 0.5, f" {word}", 0.9)
        for i, word in enumerate(WORDS)
    )
    text = "".join(word.text for word in words)
    segment = SegmentResult(0.0, len(WORDS) * 0.5, text, 0.9, words)
    return TranscriptionResult(text=text.strip(), language="pl", segments=(segment,))


@pytest.fixture
def window(qtbot, add_window) -> MainWindow:
    win = add_window(MainWindow())
    win.show()
    assert win.review.insert_draft(draft().text, draft().segments)
    return win


def replace_text(window: MainWindow, old: str, new: str, nth: int = 0) -> None:
    text = window.editor.plain_text()
    position = -1
    for _ in range(nth + 1):
        position = text.index(old, position + 1)
    cursor = QTextCursor(window.editor.document())
    cursor.setPosition(position)
    cursor.setPosition(position + len(old), QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(new)


def correct_all(window: MainWindow) -> None:
    for word in ("mleko", "chleb", "ser"):
        replace_text(window, word, word.replace("e", "y", 1))
    replace_text(window, "kartofle", "grule")
    replace_text(window, "kartofle", "grule")


def shown(controller: InsightsController) -> InsightsDialog:
    controller.run = lambda dialog: None
    controller.action.trigger()
    assert controller.dialog is not None
    return controller.dialog


def test_draft_after_rules_is_saved_in_the_project(window) -> None:
    baseline = window.review.baseline
    assert baseline is not None
    assert baseline.text == window.editor.plain_text()
    replace_text(window, "mleko", "mlyko")
    assert window.session.capture_state().draft_baseline == baseline


def test_dialog_shows_rule_proposals_and_word_replacements(window) -> None:
    correct_all(window)
    dialog = shown(window.analysis.insights)
    (rule,) = dialog.rules.insights
    assert rule.candidate.change.key[:2] == ("e", "y")
    assert len(rule.places) == 3
    insights = window.analysis.insights.insights
    assert insights is not None
    assert [(w.original, w.corrected, w.count) for w in insights.words] == [
        ("kartofle", "grule", 2)
    ]
    assert dialog.nav.item(1).text().endswith("(1)")


def test_dismissed_proposal_is_saved_in_the_profile(window) -> None:
    correct_all(window)
    controller = window.analysis.insights
    shown(controller)
    controller.dismiss_rule(0, True)
    key = window.rules_store.dismissed[0]
    assert key[:2] == ("e", "y")
    assert "[[dismissed]]" in window.profiles.current_profile().rules_toml
    assert controller.insights is not None and controller.insights.rules[0].dismissed
    # Przycisk w pasku stanu też już tego nie proponuje.
    window.learning.refresh()
    assert window.learning.candidate is None
    controller.dismiss_rule(0, False)
    assert window.rules_store.dismissed == ()


def test_create_rule_opens_the_rule_editor(window, monkeypatch) -> None:
    correct_all(window)
    opened: list[PhoneticRule] = []
    monkeypatch.setattr(window, "edit_new_rule", opened.append)
    controller = window.analysis.insights
    shown(controller)
    controller.create_rule(0)
    assert opened and opened[0].replacement == "y"


def test_words_go_to_project_or_global_vocabulary(window) -> None:
    controller = window.analysis.insights
    controller.add_words(["grule"], False)
    assert "grule" in window.asr_panel.asr_context()[1]
    assert window.session.has_unsaved_work
    controller.add_words(["Grochowskie"], True)
    assert "Grochowskie" in window.settings_store.current.asr.vocabulary_words


def test_setting_is_turned_on_in_the_profile(window) -> None:
    window.analysis.insights.enable_setting("verbatim")
    assert window.settings_store.current.asr.verbatim


def test_draft_is_estimated_from_the_asr_result_without_a_saved_one(window) -> None:
    window.review.restore_baseline(None)
    window.asr_panel.restore_result(draft())
    baseline, estimated = window.analysis.insights.baseline()
    assert estimated
    assert baseline is not None and "kartofle" in baseline.text
    window.asr_panel.restore_result(None)
    assert window.analysis.insights.baseline() == (None, True)


def test_report_export_and_menu_entries(window, tmp_path, monkeypatch) -> None:
    correct_all(window)
    controller = window.analysis.insights
    shown(controller)
    menu = window.main_toolbar.open_menu
    menu.refresh()
    actions = menu.menu.actions()
    assert actions.index(controller.action) == actions.index(menu.compare_action) + 1
    assert controller.all_action in window.learning.menu.actions()
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "raport"), "")),
    )
    assert controller.export(".csv")
    rows = list(
        csv.reader((tmp_path / "raport.csv").read_text("utf-8-sig").splitlines())
    )
    assert rows[0] == ["Rodzaj", "Wniosek", "Ile razy", "Szczegóły"]
    assert any(row[1] == "kartofle → grule" for row in rows)


def test_report_table_lists_every_kind() -> None:
    from transkryptor.notation.draft_insights import draft_insights

    baseline = Version(
        "Tak, mleko chleb ser.\nkartofle i kartofle", (), {0: "B", 1: "I"}
    )
    current = Version("tak mlyko chlyb syr nie?\ngrule i grule", (), {0: "B", 1: "B"})
    insights = draft_insights(baseline, current, ())
    kinds = {row[0] for row in insights_table(insights, current.text).rows}
    assert {"Reguły zapisu", "Słowa poprawiane w całości", "Mówcy"} <= kinds


def corpus_project(path: Path, words: int) -> None:
    baseline = " ".join(["mleko", "chleb", "ser"][:words])
    text = baseline.replace("e", "y")
    save_project(
        ProjectState(
            text=text,
            draft_baseline=Version(baseline),
            asr=AsrDraft(baseline, segments=(AsrSegment(0.0, 1.0, baseline, 0.9),)),
        ),
        path,
    )


def test_corpus_tab_sums_projects_and_adds_rules_to_the_profile(
    window, tmp_path
) -> None:
    for name in ("a", "b", "c"):
        corpus_project(tmp_path / f"{name}.transkr", 2)
    dialog = window.corpus.open_dialog()
    dialog.wait()
    dialog.set_folder(tmp_path)
    dialog.wait()
    tab = dialog.insights
    tab.repeats_spin.setValue(5)
    assert tab.analyse()
    dialog.wait()
    (rule,) = tab.shown_rules
    assert rule.projects == 3 and rule.corpus_only
    # Propozycja tylko z korpusu nie jest zaznaczona z góry.
    assert not tab.checked_rules()
    tab.set_checked(0, True)
    assert tab.add_checked()
    assert any(r.replacement == "y" for r in window.rules_store.user_rules)
    # Reguła już jest w profilu - propozycja znika.
    assert not tab.checked_rules()
