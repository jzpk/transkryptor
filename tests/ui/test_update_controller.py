"""Testy aktualizacji: ekran startowy, oferta w banerze, pobranie, ochrona pracy."""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMessageBox

from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.startup_screen import StartupScreen
from transkryptor.ui.toolbar import COLLAPSE_ORDER
from transkryptor.ui.update_controller import (
    CHECK_INTERVAL_S,
    UpdateController,
    UpdateThread,
)
from transkryptor.update.advisory import Advisory
from transkryptor.update.releases import ReleaseInfo
from transkryptor.update.service import UpdateOutcome, UpdateService, UpdateStatus

RELEASE = ReleaseInfo("9.0.0", "podpis", "linux")
ARTIFACT = Path("/tmp/Transkryptor-9.0.0-x86_64.AppImage")


class FakeService:
    """Sprawdzenie i pobranie z postępem; ``gate`` wstrzymuje koniec zadania."""

    def __init__(
        self,
        outcome: UpdateOutcome,
        gate=None,
        download: UpdateOutcome | None = None,
    ) -> None:
        self.outcome = outcome
        self.download_outcome = download or UpdateOutcome(
            UpdateStatus.READY, RELEASE, ARTIFACT
        )
        self.gate = gate
        self.cancelled = False
        self.downloads: list[ReleaseInfo] = []

    def check(self) -> UpdateOutcome:
        if self.gate is not None:
            self.gate.wait(5)
        return self.outcome

    def download(self, release, should_cancel=lambda: False, on_progress=None):
        self.downloads.append(release)
        if on_progress is not None:
            on_progress(5 << 20, 10 << 20)
        if self.gate is not None:
            self.gate.wait(5)
        self.cancelled = should_cancel()
        return self.download_outcome


def as_service(fake: FakeService) -> UpdateService:
    return cast(UpdateService, fake)


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


OFFER = UpdateOutcome(UpdateStatus.DOWNLOADABLE, RELEASE)


def use_service(window, service: FakeService) -> None:
    window.updates._service_factory = lambda: service


def run_check(qtbot, window, outcome: UpdateOutcome, service=None) -> FakeService:
    updates = window.updates
    service = service or FakeService(outcome)
    use_service(window, service)
    updates.start_automatic()
    qtbot.waitUntil(lambda: not updates.is_running, timeout=5000)
    return service


def download(qtbot, window) -> None:
    window.updates.banner.download_button.click()
    qtbot.waitUntil(lambda: not window.updates.is_downloading, timeout=5000)


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


def test_new_version_is_offered_without_downloading(qtbot, window) -> None:
    service = run_check(qtbot, window, OFFER)
    banner = window.updates.banner
    assert banner.isVisibleTo(window)
    assert banner.label.text() == tr("update.available", version="9.0.0")
    assert banner.download_button.text() == tr("update.download")
    assert banner.download_button.isVisibleTo(window)
    assert not banner.install_button.isVisibleTo(window)
    assert service.downloads == []


def test_download_button_downloads_and_installs(qtbot, window) -> None:
    applied: list[Path] = []
    window.updates._apply = applied.append
    service = run_check(qtbot, window, OFFER)
    window.show()
    download(qtbot, window)
    assert service.downloads == [RELEASE]
    assert applied == [ARTIFACT]
    assert not window.isVisible()


def test_download_shows_progress_in_the_banner(qtbot, window) -> None:
    gate = threading.Event()
    service = FakeService(OFFER)
    run_check(qtbot, window, OFFER, service)
    service.gate = gate
    banner = window.updates.banner
    banner.download_button.click()
    assert window.updates.is_downloading
    assert banner.label.text() == tr("update.downloading", version="9.0.0")
    assert not banner.download_button.isVisibleTo(window)
    qtbot.waitUntil(lambda: "50%" in banner.detail_label.text(), timeout=5000)
    window.updates._apply = lambda _artifact: None
    gate.set()
    qtbot.waitUntil(lambda: not window.updates.is_downloading, timeout=5000)


def test_failed_download_is_reported_and_offered_again(
    qtbot, window, no_blocking_dialogs
) -> None:
    failed = UpdateOutcome(UpdateStatus.ERROR, RELEASE, error=UpdateError("błąd"))
    run_check(qtbot, window, OFFER, FakeService(OFFER, download=failed))
    download(qtbot, window)
    assert [k for k, _t, _x in no_blocking_dialogs] == ["warning"]
    assert window.updates.banner.download_button.isVisibleTo(window)


def test_offline_download_is_reported(qtbot, window, no_blocking_dialogs) -> None:
    offline = UpdateOutcome(UpdateStatus.OFFLINE, RELEASE)
    run_check(qtbot, window, OFFER, FakeService(OFFER, download=offline))
    download(qtbot, window)
    [(kind, _title, text)] = no_blocking_dialogs
    assert kind == "warning"
    assert tr("update.error.offline") in text


def test_available_update_is_reported_without_download_link(qtbot, window) -> None:
    run_check(qtbot, window, UpdateOutcome(UpdateStatus.AVAILABLE, RELEASE))
    banner = window.updates.banner
    assert banner.isVisibleTo(window)
    text = banner.label.text()
    assert text == tr("update.available", version="9.0.0")
    assert "href" not in text and RELEASE.page_url not in text
    assert not banner.download_button.isVisibleTo(window)
    assert not banner.install_button.isVisibleTo(window)


@pytest.mark.parametrize(
    "status",
    [
        UpdateStatus.OFFLINE,
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
    run_check(qtbot, window, OFFER)
    window.editor.setPlainText("niewyeksportowany tekst")
    window.show()

    download(qtbot, window)  # ochrona sesji: odpowiedź „nie”
    assert applied == []
    assert window.isVisible()
    assert [k for k, _t, _x in no_blocking_dialogs] == ["question"]
    banner = window.updates.banner
    assert banner.label.text() == tr("update.ready", version="9.0.0")
    assert banner.install_button.isVisibleTo(window)

    window.document.mark_exported()
    banner.install_button.click()
    assert applied == [ARTIFACT]
    assert not window.isVisible()


def test_failed_install_is_reported(qtbot, window, no_blocking_dialogs) -> None:
    def fail(_artifact: Path) -> None:
        raise UpdateError("Nie udało się podmienić pliku.")

    window.updates._apply = fail
    run_check(qtbot, window, OFFER)
    download(qtbot, window)
    assert [k for k, _t, _x in no_blocking_dialogs] == ["warning"]
    assert window.updates.banner.download_button.isVisibleTo(window)


def test_banner_text_is_not_html(window) -> None:
    window.updates.banner.show_offer('9.0.0"><b>x</b>', can_download=True)
    assert window.updates.banner.label.textFormat() == Qt.TextFormat.PlainText


# --- ekran startowy -------------------------------------------------------------


def test_startup_screen_closes_when_check_is_done(qtbot) -> None:
    screen = StartupScreen()
    qtbot.addWidget(screen)
    assert screen.status_label.text() == tr("startup.checking")
    screen.finish()
    screen.wait()  # zakończony ekran nie blokuje
    assert screen.is_done


def test_startup_check_hands_result_to_window(qtbot, add_window) -> None:
    """Okno powstaje w trakcie sprawdzania i dostaje gotowy wynik."""
    service = FakeService(OFFER)
    screen = StartupScreen()
    qtbot.addWidget(screen)
    thread = UpdateThread.checking(as_service(service))
    screen.attach(thread)
    thread.start()
    window = add_window(MainWindow())
    screen.wait()
    assert screen.is_done
    window.updates.adopt(thread)
    qtbot.waitUntil(lambda: not window.updates.is_running, timeout=5000)
    assert window.updates.banner.download_button.isVisibleTo(window)
    assert service.downloads == []


def test_skipped_startup_check_finishes_in_background(qtbot, add_window) -> None:
    gate = threading.Event()
    service = FakeService(OFFER, gate)
    screen = StartupScreen()
    qtbot.addWidget(screen)
    thread = UpdateThread.checking(as_service(service))
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
    assert window.updates.banner.download_button.isVisibleTo(window)
    assert service.downloads == []


def test_escape_skips_startup_screen(qtbot) -> None:
    screen = StartupScreen()
    qtbot.addWidget(screen)
    with qtbot.waitSignal(screen.skipped):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)
    assert screen.is_done


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def periodic(qtbot):
    """Kontroler z zegarem testowym; liczy przebiegi sprawdzania."""
    host = QMainWindow()
    qtbot.addWidget(host)
    clock = Clock()
    runs: list[FakeService] = []
    outcome = [UpdateOutcome(UpdateStatus.UP_TO_DATE)]

    def factory() -> UpdateService:
        service = FakeService(outcome[0])
        runs.append(service)
        return as_service(service)

    controller = UpdateController(host, service_factory=factory, clock=clock)

    def check() -> None:
        controller.check_if_due()
        qtbot.waitUntil(lambda: not controller.is_running, timeout=5000)

    return controller, clock, runs, outcome, check


def test_periodic_checks_start_with_the_first_check(periodic) -> None:
    controller, _clock, runs, _outcome, check = periodic
    assert not controller.periodic_checks_active
    check()  # pierwsze sprawdzenie (np. przy starcie)
    assert len(runs) == 1
    assert controller.periodic_checks_active
    controller.shutdown()
    assert not controller.periodic_checks_active


def test_background_check_repeats_every_six_hours(periodic) -> None:
    controller, clock, runs, _outcome, check = periodic
    check()
    clock.now += CHECK_INTERVAL_S - 1
    check()
    assert len(runs) == 1
    # Także po uśpieniu komputera: liczy się zegar ścienny.
    clock.now += 2
    check()
    assert len(runs) == 2
    check()
    assert len(runs) == 2


def test_new_release_found_in_background_is_offered(periodic) -> None:
    controller, clock, runs, outcome, check = periodic
    check()
    assert not controller.banner.isVisibleTo(controller.parent())
    outcome[0] = OFFER
    clock.now += CHECK_INTERVAL_S
    check()
    banner = controller.banner
    assert banner.label.text() == tr("update.available", version="9.0.0")
    assert banner.download_button.isVisibleTo(controller.parent())
    assert runs[-1].downloads == []
    # Oferta nie wstrzymuje sprawdzania - może pojawić się nowsza wersja.
    assert controller.periodic_checks_active


# --- ostrzeżenie o luce w bieżącej wersji ---------------------------------------

ADVISORY = Advisory(1, "9.0.0", (("en", "Security hole."), ("pl", "Luka <b>x</b>.")))
URGENT = UpdateOutcome(UpdateStatus.DOWNLOADABLE, RELEASE, advisory=ADVISORY)


def wait_dialogs(qtbot, calls, count: int = 1):
    qtbot.waitUntil(lambda: len(calls) >= count, timeout=5000)
    return calls


def test_advisory_downloads_without_a_click_and_asks(
    qtbot, window, no_blocking_dialogs
) -> None:
    applied: list[Path] = []
    window.updates._apply = applied.append
    service = run_check(qtbot, window, URGENT)
    [(kind, title, text)] = wait_dialogs(qtbot, no_blocking_dialogs)
    assert service.downloads == [RELEASE]
    assert kind == "question"
    assert title == tr("update.advisory.title")
    assert "Luka &lt;b&gt;x&lt;/b&gt;." in text  # treść z pliku bez HTML
    assert applied == []  # odpowiedź „nie” - instalacja później z banera
    assert window.updates.banner.install_button.isVisibleTo(window)


def test_accepted_advisory_installs_now(qtbot, window, monkeypatch) -> None:
    applied: list[Path] = []
    window.updates._apply = applied.append
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kw: QMessageBox.StandardButton.Yes),
    )
    run_check(qtbot, window, URGENT)
    qtbot.waitUntil(lambda: applied == [ARTIFACT], timeout=5000)


def test_failed_urgent_download_only_warns(qtbot, window, no_blocking_dialogs) -> None:
    failed = UpdateOutcome(UpdateStatus.ERROR, RELEASE, error=UpdateError("błąd"))
    run_check(qtbot, window, URGENT, FakeService(URGENT, download=failed))
    [(kind, title, _text)] = wait_dialogs(qtbot, no_blocking_dialogs)
    assert (kind, title) == ("warning", tr("update.advisory.title"))
    assert window.updates.banner.download_button.isVisibleTo(window)


def test_advisory_without_self_update_only_warns(
    qtbot, window, no_blocking_dialogs
) -> None:
    outcome = UpdateOutcome(UpdateStatus.AVAILABLE, RELEASE, advisory=ADVISORY)
    service = run_check(qtbot, window, outcome)
    [(kind, _title, _text)] = wait_dialogs(qtbot, no_blocking_dialogs)
    assert kind == "warning"
    assert service.downloads == []


def test_advisory_is_shown_once_per_session(qtbot, window, no_blocking_dialogs) -> None:
    outcome = UpdateOutcome(UpdateStatus.OFFLINE, advisory=ADVISORY)
    run_check(qtbot, window, outcome)
    wait_dialogs(qtbot, no_blocking_dialogs)
    run_check(qtbot, window, outcome)
    qtbot.wait(50)
    assert len(no_blocking_dialogs) == 1
