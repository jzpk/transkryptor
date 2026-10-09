"""Testy aktualizacji w oknie głównym: baner, komunikaty, ochrona pracy."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.ui.main_window import MainWindow
from transkryptor.update.releases import ReleaseInfo
from transkryptor.update.service import UpdateOutcome, UpdateStatus

RELEASE = ReleaseInfo(
    "9.0.0", "https://github.com/jzpk/transkryptor/releases/tag/v9.0.0", None, None
)
ARTIFACT = Path("/tmp/Transkryptor-9.0.0-x86_64.AppImage")


class FakeService:
    def __init__(self, outcome: UpdateOutcome) -> None:
        self.outcome = outcome

    def run(self, should_cancel=lambda: False) -> UpdateOutcome:
        return self.outcome


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def run_check(qtbot, window, outcome: UpdateOutcome, *, manual: bool) -> None:
    updates = window.updates
    updates._service_factory = lambda: FakeService(outcome)
    if manual:
        updates.check_now()
    else:
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
    run_check(qtbot, window, outcome, manual=False)
    assert window.updates.banner.isVisibleTo(window)
    assert "9.0.0" in window.updates.banner_label.text()
    assert window.updates.install_button.text() == tr("update.install")
    assert window.updates.install_button.isVisibleTo(window)


def test_available_update_shows_link_without_install(qtbot, window) -> None:
    run_check(
        qtbot, window, UpdateOutcome(UpdateStatus.AVAILABLE, RELEASE), manual=False
    )
    assert window.updates.banner.isVisibleTo(window)
    assert RELEASE.page_url in window.updates.banner_label.text()
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
    run_check(qtbot, window, UpdateOutcome(status, error=error), manual=False)
    assert no_blocking_dialogs == []
    assert not window.updates.banner.isVisibleTo(window)


@pytest.mark.parametrize(
    ("status", "kind", "text"),
    [
        (UpdateStatus.OFFLINE, "warning", tr("update.offline")),
        (UpdateStatus.QUOTA_EXHAUSTED, "information", tr("update.quota")),
    ],
)
def test_manual_check_always_answers(
    qtbot, window, no_blocking_dialogs, status, kind, text
) -> None:
    run_check(qtbot, window, UpdateOutcome(status), manual=True)
    assert [(k, t) for k, _title, t in no_blocking_dialogs] == [(kind, text)]


def test_manual_check_reports_up_to_date(qtbot, window, no_blocking_dialogs) -> None:
    run_check(qtbot, window, UpdateOutcome(UpdateStatus.UP_TO_DATE), manual=True)
    ((kind, _title, text),) = no_blocking_dialogs
    assert kind == "information"
    assert "najnowszą wersję" in text


def test_check_action_is_in_the_toolbar(window) -> None:
    button = window.main_toolbar.button_for(window.updates.check_action)
    assert button.defaultAction() is window.updates.check_action
    assert button.parent() is window.toolbar


def test_install_respects_unsaved_work(qtbot, window, no_blocking_dialogs) -> None:
    applied: list[Path] = []
    window.updates._apply = applied.append
    run_check(
        qtbot,
        window,
        UpdateOutcome(UpdateStatus.READY, RELEASE, ARTIFACT),
        manual=False,
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
        manual=False,
    )
    window.updates.install_button.click()
    assert [k for k, _t, _x in no_blocking_dialogs] == ["warning"]
