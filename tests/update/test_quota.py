"""Testy dziennego limitu zapytań do GitHub API."""

from __future__ import annotations

import json
from datetime import date

import pytest

from transkryptor.update.quota import DAILY_LIMIT, RequestQuota
from transkryptor.update.releases import Asset, ReleaseInfo

PAGE = "https://github.com/jzpk/transkryptor/releases/tag/v1.0.0"
FILES = "https://github.com/jzpk/transkryptor/releases/download/v1.0.0"
TODAY = date(2026, 10, 8)
TOMORROW = date(2026, 10, 9)


def test_limit_is_two_requests_per_day() -> None:
    assert DAILY_LIMIT == 2


def test_third_request_on_the_same_day_is_refused(tmp_path) -> None:
    quota = RequestQuota(tmp_path / "state.json")
    assert quota.try_acquire(TODAY)
    assert quota.try_acquire(TODAY)
    assert not quota.try_acquire(TODAY)
    assert quota.remaining(TODAY) == 0


def test_counter_survives_restart(tmp_path) -> None:
    path = tmp_path / "state.json"
    RequestQuota(path).try_acquire(TODAY)
    RequestQuota(path).try_acquire(TODAY)
    assert not RequestQuota(path).try_acquire(TODAY)


def test_new_day_discards_old_state(tmp_path) -> None:
    path = tmp_path / "state.json"
    quota = RequestQuota(path)
    quota.try_acquire(TODAY)
    quota.try_acquire(TODAY)
    quota.remember(TODAY, ReleaseInfo("1.0.0", PAGE, None, None))

    assert quota.remaining(TOMORROW) == 2
    assert quota.cached_release(TOMORROW) is None
    assert quota.try_acquire(TOMORROW)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {"date": "2026-10-09", "requests": 1, "latest": None}


def test_refund_returns_a_reservation(tmp_path) -> None:
    quota = RequestQuota(tmp_path / "state.json")
    quota.try_acquire(TODAY)
    quota.refund(TODAY)
    assert quota.remaining(TODAY) == 2
    quota.refund(TODAY)
    assert quota.remaining(TODAY) == 2


def test_cached_release_is_kept_for_the_day(tmp_path) -> None:
    quota = RequestQuota(tmp_path / "state.json")
    release = ReleaseInfo(
        "1.0.0",
        PAGE,
        Asset("a.AppImage", f"{FILES}/a.AppImage", 5),
        Asset("SHA256SUMS.txt", f"{FILES}/SHA256SUMS.txt", 1),
        Asset("SHA256SUMS.txt.minisig", f"{FILES}/SHA256SUMS.txt.minisig", 1),
    )
    quota.remember(TODAY, release)
    assert RequestQuota(quota.path).cached_release(TODAY) == release


def test_corrupted_state_file_means_empty_state(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{to nie jest json", encoding="utf-8")
    quota = RequestQuota(path)
    assert quota.remaining(TODAY) == 2
    path.write_text(json.dumps({"date": TODAY.isoformat(), "requests": "x"}))
    assert quota.remaining(TODAY) == 2
    path.write_text(json.dumps({"date": TODAY.isoformat(), "latest": {"a": 1}}))
    assert quota.cached_release(TODAY) is None


def test_unwritable_state_still_limits_the_session(tmp_path) -> None:
    blocker = tmp_path / "plik"
    blocker.write_text("", encoding="utf-8")
    quota = RequestQuota(blocker / "state.json")  # katalog nadrzędny to plik
    assert quota.try_acquire(TODAY)
    assert quota.try_acquire(TODAY)
    assert not quota.try_acquire(TODAY)


@pytest.mark.parametrize(
    "tampered",
    [
        {"version": "../../poza-pamiecia"},
        {"page_url": "javascript:alert(1)"},
        {"artifact": {"name": "../a.AppImage", "url": f"{FILES}/a", "size": 1}},
        {"artifact": {"name": "a.AppImage", "url": "http://github.com/a", "size": 1}},
        {"checksums": {"name": "S", "url": "https://evil.example/S", "size": 1}},
    ],
)
def test_tampered_state_file_release_is_ignored(tmp_path, tampered) -> None:
    """Plik stanu w katalogu użytkownika nie może wskazać ścieżki ani adresu."""
    quota = RequestQuota(tmp_path / "state.json")
    quota.remember(TODAY, ReleaseInfo("1.0.0", PAGE, None, None))
    stored = json.loads(quota.path.read_text(encoding="utf-8"))
    stored["latest"].update(tampered)
    quota.path.write_text(json.dumps(stored), encoding="utf-8")
    assert quota.cached_release(TODAY) is None
