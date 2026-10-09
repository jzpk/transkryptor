"""Nakładka ładowania: rotacja zabawnych tekstów i anulowanie."""

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QWidget

from transkryptor.i18n import tr
from transkryptor.ui.loading_overlay import (
    LoadingOverlay,
    format_remaining,
    loading_messages,
)


def make_overlay(qtbot, **kwargs) -> tuple[QWidget, LoadingOverlay]:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    return host, LoadingOverlay(host, **kwargs)


def test_has_thirty_distinct_messages() -> None:
    assert len(loading_messages()) == 30
    assert len(set(loading_messages())) == 30


def test_every_message_shown_before_any_repeats(qtbot) -> None:
    _host, overlay = make_overlay(qtbot)
    overlay.start()
    seen = [overlay.message_label.text()]
    for _ in range(len(loading_messages()) - 1):
        overlay.next_message()
        seen.append(overlay.message_label.text())
    assert sorted(seen) == sorted(loading_messages())
    overlay.stop()


def test_message_never_repeats_back_to_back(qtbot) -> None:
    _host, overlay = make_overlay(qtbot, messages=("a", "b"))
    previous = overlay.message_label.text()
    for _ in range(50):
        overlay.next_message()
        current = overlay.message_label.text()
        assert current != previous
        previous = current


def test_message_rotates_on_timer(qtbot) -> None:
    _host, overlay = make_overlay(qtbot, interval_ms=20)
    overlay.start()
    first = overlay.message_label.text()
    qtbot.waitUntil(lambda: overlay.message_label.text() != first, timeout=2000)
    overlay.stop()


def test_overlay_covers_parent_and_follows_resize(qtbot) -> None:
    host, overlay = make_overlay(qtbot)
    host.show()  # ukryty rodzic odkłada zdarzenia Resize do pokazania
    overlay.start()
    assert overlay.geometry() == host.rect()
    host.resize(1000, 700)
    assert overlay.geometry() == host.rect()
    overlay.stop()
    assert not overlay.isVisibleTo(host)


def test_cancel_emits_signal_once(qtbot) -> None:
    _host, overlay = make_overlay(qtbot)
    overlay.start()
    spy = QSignalSpy(overlay.cancel_requested)
    overlay.cancel_button.click()
    assert spy.count() == 1
    assert not overlay.cancel_button.isEnabled()
    overlay.stop()


def test_spinner_shows_percent_once_progress_is_known(qtbot) -> None:
    _host, overlay = make_overlay(qtbot)
    overlay.start()
    assert overlay.spinner.progress() is None
    assert overlay.spinner.percent_text() == ""
    overlay.set_progress(0.426)
    assert overlay.spinner.percent_text() == "42%"
    overlay.set_progress(1.7)  # wartości spoza zakresu są przycinane
    assert overlay.spinner.percent_text() == "100%"
    overlay.spinner.grab()  # rysowanie gradientu i tekstu nie rzuca wyjątków
    overlay.stop()


def test_restart_resets_progress(qtbot) -> None:
    _host, overlay = make_overlay(qtbot)
    overlay.start()
    overlay.set_progress(0.8)
    overlay.stop()
    overlay.start()
    assert overlay.spinner.progress() is None
    overlay.stop()


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (-5, "Jeszcze chwila…"),
        (30, "Pozostało mniej niż minuta"),
        (61, "Pozostało ok. 2 min"),
        (600, "Pozostało ok. 10 min"),
        (3600, "Pozostało ok. 1 godz."),
        (5400, "Pozostało ok. 1 godz. 30 min"),
    ],
)
def test_format_remaining(seconds, text) -> None:
    assert format_remaining(seconds) == text


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_eta_waits_for_stable_rate_then_extrapolates(qtbot) -> None:
    clock = FakeClock()
    _host, overlay = make_overlay(qtbot, clock=clock)
    overlay.start()
    # Pierwsza próbka po ładowaniu modelu — tempo jeszcze nieznane.
    clock.now += 60
    overlay.set_progress(0.1)
    assert overlay.eta_label.text() == tr("loading.eta_pending")
    clock.now += 5  # za krótko na wiarygodny szacunek
    overlay.set_progress(0.12)
    assert overlay.eta_label.text() == tr("loading.eta_pending")
    # 0.1 nagrania w 60 s → pozostałe 0.8 to ok. 480 s = 8 min.
    clock.now += 55
    overlay.set_progress(0.2)
    assert overlay.eta_label.text() == "Pozostało ok. 8 min"
    # Między próbkami licznik odlicza w dół.
    clock.now += 360
    overlay._refresh_eta()
    assert overlay.eta_label.text() == "Pozostało ok. 2 min"
    overlay.stop()
    overlay.start()
    assert overlay.eta_label.text() == tr("loading.eta_pending")
    overlay.stop()
