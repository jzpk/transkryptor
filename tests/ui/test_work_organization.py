"""Organizacja pracy w oknie: czas pracy, statystyki, migawki i menu paczki."""

import csv
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.document.project import ProjectState
from transkryptor.document.work_log import WorkDay, WorkLog
from transkryptor.settings import ProjectSettings, Settings
from transkryptor.ui.history_dialog import COMPARE, RESTORE, HistoryDialog
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.stats_dialog import StatsDialog
from transkryptor.ui.work_time import IDLE_LIMIT_S, WorkTimeTracker

Button = QMessageBox.StandardButton


@pytest.fixture
def window(add_window) -> MainWindow:
    return add_window(MainWindow())


def type_text(window: MainWindow, text: str) -> None:
    window.editor.setPlainText(text)
    window.session.flush_editor()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestWorkTime:
    def tracker(self, window, clock, coverage=lambda: 0) -> WorkTimeTracker:
        return WorkTimeTracker(window.player, coverage, clock, lambda: "2026-10-31")

    def test_activity_counts_and_idle_does_not(self, window) -> None:
        clock = FakeClock()
        tracker = self.tracker(window, clock, coverage=lambda: 4000)
        tracker.register_activity()
        clock.now += 30
        tracker.register_activity()
        clock.now += IDLE_LIMIT_S + 1  # przerwa na kawę
        tracker.register_activity()
        clock.now += 10.6
        tracker.register_activity()
        assert tracker.log.seconds == 40
        assert tracker.log.days == (WorkDay("2026-10-31", 40, 4000),)

    def test_restore_and_clear(self, window) -> None:
        clock = FakeClock()
        tracker = self.tracker(window, clock)
        tracker.restore(WorkLog(100))
        clock.now += 5
        tracker.register_activity()  # pierwsza aktywność po otwarciu
        assert tracker.log.seconds == 100
        tracker.clear()
        assert tracker.log == WorkLog()

    def test_editing_is_activity_and_work_time_is_saved(
        self, window, tmp_path, monkeypatch
    ) -> None:
        clock = FakeClock()
        window.work_time.clock = clock
        window.work_time.restore(WorkLog(60))
        window.editor.insertPlainText("raz")
        clock.now += 20
        window.editor.insertPlainText(" dwa")
        assert window.session.capture_state().work.seconds == 80

        path = tmp_path / "praca.transkr"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(path), "")),
        )
        assert window.session.save_project()
        window.session.new_document()
        assert window.work_time.log.seconds == 0
        assert window.session.open_project(path)
        assert window.work_time.log.seconds == 80


class TestStats:
    def test_dialog_shows_progress_and_exports_csv(
        self, window, tmp_path, monkeypatch
    ) -> None:
        state = ProjectState(
            text="raz dwa trzy",
            anchors=(Anchor(0, 12, 0, 30_000, SEGMENT),),
            verified=((0, 15_000),),
            work=WorkLog(1800, 60_000),
        )
        window.session.apply_state(state, None, None, saved=True)
        shown: list[StatsDialog] = []

        def record(dialog: StatsDialog) -> int:
            shown.append(dialog)
            return 0

        window.progress.run = record
        window.progress.stats_action.trigger()
        dialog = shown[0]
        values = {str(name): value for name, value in dialog.rows}
        assert values["Przetranskrybowano"] == "50%"
        assert values["Zweryfikowano"] == "25%"
        assert values["Czas pracy"] == "0:30:00"
        assert values["Liczba słów"] == 3

        target = tmp_path / "statystyki.csv"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(tmp_path / "statystyki"), "")),
        )
        assert dialog.export(".csv")
        rows = list(csv.reader(target.read_text(encoding="utf-8-sig").splitlines()))
        assert rows[0] == ["Statystyka", "Wartość"]
        assert ["Przetranskrybowano", "50%"] in rows

    def test_action_is_in_export_menu(self, window) -> None:
        actions = window.main_toolbar.export_menu.actions()
        assert window.progress.stats_action in actions
        assert window.packs.export_action in actions

    def test_daily_goal_label(self, window) -> None:
        assert window.progress.goal_label.isHidden()
        current = window.settings_store.current
        window.settings_store.save(
            replace(current, project=replace(current.project, daily_goal_min=20))
        )
        assert not window.progress.goal_label.isHidden()
        assert window.progress.goal_label.text() == "Dziś: 0/20 min nagrania"

    def test_daily_goal_setting_round_trip(self, qtbot) -> None:
        settings = Settings(project=ProjectSettings(daily_goal_min=25))
        dialog = SettingsDialog(settings)
        qtbot.addWidget(dialog)
        assert dialog.project_page.daily_goal_spin.value() == 25
        dialog.project_page.daily_goal_spin.setValue(0)
        assert dialog.settings().project.daily_goal_min == 0


class TestSnapshots:
    def test_manual_snapshot_and_restore_can_be_undone(
        self, window, monkeypatch
    ) -> None:
        type_text(window, "pierwsza wersja")
        window.snapshots.ask_label = lambda: "przed recenzją"
        window.snapshots.save_action.trigger()
        type_text(window, "druga wersja tekstu")

        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: Button.Yes)
        )
        snapshot = window.snapshots.store.list()[0]
        assert snapshot.label == "przed recenzją"
        assert window.snapshots.restore(snapshot)
        assert window.editor.toPlainText() == "pierwsza wersja"
        assert window.session.has_unsaved_work

        # Stan sprzed przywrócenia jest migawką automatyczną.
        before = window.snapshots.store.list()[0]
        assert before.automatic
        assert window.snapshots.restore(before, confirm=False)
        assert window.editor.toPlainText() == "druga wersja tekstu"

    def test_automatic_snapshot_before_unifying_ellipses(self, window) -> None:
        type_text(window, "no to... tak")
        window.unify_ellipses_action.trigger()
        snapshots = window.snapshots.store.list()
        assert [s.automatic for s in snapshots] == [True]
        assert window.snapshots.store.load(snapshots[0]).text == "no to... tak"

    def test_no_automatic_snapshot_of_empty_work(self, window) -> None:
        window.review.draft_about_to_insert.emit()
        assert window.snapshots.store.list() == []

    def test_automatic_snapshot_before_asr_draft(self, window) -> None:
        type_text(window, "ręczny tekst")
        window._ask_draft_placement = lambda: "replace"
        window.asr.insert_draft("szkic z ASR")
        snapshots = window.snapshots.store.list()
        assert len(snapshots) == 1
        assert window.snapshots.store.load(snapshots[0]).text == "ręczny tekst"

    def test_history_compares_with_current(self, window) -> None:
        type_text(window, "stary tekst")
        window.snapshots.save("wersja 1")
        type_text(window, "nowy tekst")

        def choose(dialog: HistoryDialog) -> int:
            dialog.select(0)
            dialog.choose(COMPARE)
            return COMPARE

        window.snapshots.run_history = choose
        window.snapshots.history_action.trigger()
        assert window.compare.active
        assert window.compare_view.toPlainText() == "stary tekst"
        window.compare.finish()

    def test_history_restore_asks_first(self, window) -> None:
        type_text(window, "stary tekst")
        window.snapshots.save("wersja 1")
        type_text(window, "nowy tekst")

        def choose(dialog: HistoryDialog) -> int:
            dialog.choose(RESTORE)
            return RESTORE

        window.snapshots.run_history = choose
        window.snapshots.history()  # pytanie: domyślnie „nie”
        assert window.editor.toPlainText() == "nowy tekst"

    def test_session_snapshots_move_to_saved_project(
        self, window, tmp_path, monkeypatch, isolated_snapshots
    ) -> None:
        type_text(window, "tekst")
        window.snapshots.save("bez pliku")
        path = tmp_path / "projekt.transkr"
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(path), "")),
        )
        assert window.session.save_project()
        assert [s.label for s in window.snapshots.store.list()] == ["bez pliku"]
        assert window.snapshots.store.directory.name.startswith("project-")

    def test_snapshot_actions_are_in_save_menu(self, window) -> None:
        actions = window.main_toolbar.save_menu.actions()
        assert window.snapshots.save_action in actions
        assert window.snapshots.history_action in actions


class TestLocking:
    def test_actions_are_locked_during_asr(self, window) -> None:
        window._set_ui_locked(True)
        assert not window.snapshots.save_action.isEnabled()
        assert not window.progress.stats_action.isEnabled()
        assert not window.packs.export_action.isEnabled()
        window._set_ui_locked(False)
        assert window.packs.open_action.isEnabled()


def test_open_menu_offers_pack(window) -> None:
    window.main_toolbar.refresh_recent_menu()
    assert window.packs.open_action in window.main_toolbar.open_menu.actions()


def test_pack_drop_detection() -> None:
    from transkryptor.ui.pack_controller import pack_in

    assert pack_in([Path("a.mp3"), Path("b.TKPACK")]) == Path("b.TKPACK")
    assert pack_in([Path("a.transkr")]) is None
