"""Testy aktualizacji: ekran startowy, baner w oknie, ochrona pracy."""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.startup_screen import StartupScreen
from transkryptor.ui.toolbar import COLLAPSE_ORDER
from transkryptor.ui.update_controller import UpdateThread
from transkryptor.update.releases import ReleaseInfo
from transkryptor.update.service import (
    UpdateOutcome,
    UpdateService,
    UpdateStage,
    UpdateStatus,
)

RELEASE = ReleaseInfo(
    "9.0.0", "https://github.com/jzpk/transkryptor/releases/tag/v9.0.0", None, None
)
ARTIFACT = Path("/tmp/Transkryptor-9.0.0-x86_64.AppImage")


class FakeService:
    """Przebieg z etapami i postępem pobierania; ``gate`` wstrzymuje koniec."""

    def __init__(self, outcome: UpdateOutcome, gate=None) -> None:
        self.outcome = outcome
        self.gate = gate
        self.cancelled = False

    def run(self, should_cancel=lambda: False, on_progress=None, on_stage=None):
        if on_stage is not None:
            on_stage(UpdateStage.CHECKING, None)
            if self.outcome.status is UpdateStatus.READY:
                on_stage(UpdateStage.DOWNLOADING, self.outcome.release)
        if on_progress is not None and self.outcome.status is UpdateStatus.READY:
            on_progress(5 << 20, 10 << 20)
        if self.gate is not None:
            self.gate.wait(5)
        self.cancelled = should_cancel()
        return self.outcome


def as_service(fake: FakeService) -> UpdateService:
    return cast(UpdateService, fake)


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def run_check(qtbot, window, outcome: UpdateOutcome) -> None:
    updates = window.updates
    updates._service_factory = lambda: FakeService(outcome)
    updates.start_automatic()
    qtbot.waitUntil(lambda: not updates.is_running, timeout=5000)


def test_creating_the_window_does_not_touch_the_network(
    monkeypatch, add_window
) -> None:
    """Sprawdzanie startuje punkt wejścia, nie konstruktor okna (testy UI)."""

    def deny(*_args, **_kwargs):
        raise AssertionError("okno otworzyło połączenie sieciowe")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    window = add_window(MainWindow())
    assert not window.updates.is_running


def test_ready_update_shows_banner_with_install_button(qtbot, window) -> None:
    outcome = UpdateOutcome(UpdateStatus.READY, RELEASE, ARTIFACT)
    run_check(qtbot, window, outcome)
    assert window.updates.banner.isVisibleTo(window)
    assert "9.0.0" in window.updates.banner_label.text()
    assert window.updates.install_button.text() == tr("update.install")
    assert window.updates.install_button.isVisibleTo(window)


def test_available_update_is_reported_without_download_link(qtbot, window) -> None:
    run_check(qtbot, window, UpdateOutcome(UpdateStatus.AVAILABLE, RELEASE))
    assert window.updates.banner.isVisibleTo(window)
    text = window.updates.banner_label.text()
    assert text == tr("update.available", version="9.0.0")
    assert "href" not in text and RELEASE.page_url not in text
    assert not window.updates.install_button.isVisibleTo(window)


@pytest.mark.parametrize(
    "status",
    [
        UpdateStatus.OFFLINE,
        UpdateStatus.QUOTA_EXHAUSTED,
        UpdateStatus.UP_TO_DATE,
        UpdateStatus.ERROR,
    ],
)
def test_automatic_check_is_silent(qtbot, window, no_blocking_dialogs, status) -> None:
    error = UpdateError("błąd") if status is UpdateStatus.ERROR else None
    run_check(qtbot, window, UpdateOutcome(status, error=error))
    assert no_blocking_dialogs == []
    assert not window.updates.banner.isVisibleTo(window)


def test_no_manual_update_button(window) -> None:
    """Sprawdzanie jest tylko przy starcie - bez przycisku na pasku."""
    assert "update" not in COLLAPSE_ORDER
    assert not hasattr(window.updates, "check_action")
    texts = [action.text() for action in window.findChildren(QAction)]
    assert "Sprawdź aktualizacje" not in texts


def test_install_respects_unsaved_work(qtbot, window, no_blocking_dialogs) -> None:
    applied: list[Path] = []
    window.updates._apply = applied.append
    run_check(
        qtbot,
        window,
        UpdateOutcome(UpdateStatus.READY, RELEASE, ARTIFACT),
    )
    window.editor.setPlainText("niewyeksportowany tekst")
    window.show()

    window.updates.install_button.click()  # ochrona sesji: odpowiedź „nie”
    assert applied == []
    assert window.isVisible()
    assert [k for k, _t, _x in no_blocking_dialogs] == ["question"]

    window.document.mark_exported()
    window.updates.install_button.click()
    assert applied == [ARTIFACT]
    assert not window.isVisible()


def test_failed_install_is_reported(qtbot, window, no_blocking_dialogs) -> None:
    def fail(_artifact: Path) -> None:
        raise UpdateError("Nie udało się podmienić pliku.")

    window.updates._apply = fail
    run_check(
        qtbot,
        window,
        UpdateOutcome(UpdateStatus.READY, RELEASE, ARTIFACT),
    )
    window.updates.install_button.click()
    assert [k for k, _t, _x in no_blocking_dialogs] == ["warning"]


def test_banner_text_is_not_html(window) -> None:
    window.updates._show_available('9.0.0"><b>x</b>')
    assert window.updates.banner_label.textFormat() == Qt.TextFormat.PlainText


# --- ekran startowy -------------------------------------------------------------


def test_startup_screen_shows_stages_and_closes_when_done(qtbot) -> None:
    screen = StartupScreen()
    qtbot.addWidget(screen)
    assert screen.status_label.text() == tr("startup.checking")
    screen.set_stage(UpdateStage.DOWNLOADING, RELEASE)
    assert screen.status_label.text() == tr("startup.downloading", version="9.0.0")
    screen.set_progress(5 << 20, 10 << 20)
    assert screen.progress.value() * 2 == screen.progress.maximum()
    assert "50%" in screen.detail_label.text()
    screen.set_progress(1 << 20, None)
    assert screen.progress.maximum() == 0  # bez całości - pasek nieokreślony
    screen.finish()
    screen.wait()  # zakończony ekran nie blokuje
    assert screen.is_done


def test_startup_check_hands_result_to_window(qtbot, add_window) -> None:
    """Okno powstaje w trakcie sprawdzania i dostaje gotowy wynik."""
    screen = StartupScreen()
    qtbot.addWidget(screen)
    thread = UpdateThread(
        as_service(FakeService(UpdateOutcome(UpdateStatus.READY, RELEASE, ARTIFACT)))
    )
    screen.attach(thread)
    stages: list[object] = []
    thread.stage_changed.connect(lambda stage, _release: stages.append(stage))
    thread.start()
    window = add_window(MainWindow())
    screen.wait()
    assert screen.is_done
    window.updates.adopt(thread)
    qtbot.waitUntil(lambda: not window.updates.is_running, timeout=5000)
    assert window.updates.install_button.isVisibleTo(window)
    assert stages == [UpdateStage.CHECKING, UpdateStage.DOWNLOADING]
    assert tr("startup.downloading", version="9.0.0") == screen.status_label.text()


def test_skipped_startup_check_finishes_in_background(qtbot, add_window) -> None:
    gate = threading.Event()
    service = FakeService(UpdateOutcome(UpdateStatus.READY, RELEASE, ARTIFACT), gate)
    screen = StartupScreen()
    qtbot.addWidget(screen)
    thread = UpdateThread(as_service(service))
    screen.attach(thread)
    thread.start()
    window = add_window(MainWindow())
    screen.skip_button.click()
    screen.wait()
    assert screen.is_done
    window.updates.adopt(thread)
    assert window.updates.is_running
    assert not window.updates.banner.isVisibleTo(window)
    gate.set()
    qtbot.waitUntil(lambda: not window.updates.is_running, timeout=5000)
    assert not service.cancelled
    assert window.updates.install_button.isVisibleTo(window)


def test_escape_skips_startup_screen(qtbot) -> None:
    screen = StartupScreen()
    qtbot.addWidget(screen)
    with qtbot.waitSignal(screen.skipped):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)
    assert screen.is_done
