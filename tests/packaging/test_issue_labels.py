"""Testy etykiet wersji: które zgłoszenia dostają numer wydania."""

from datetime import UTC, datetime

import pytest

from transkryptor.packaging.issue_labels import (
    GitHubIssues,
    LabelError,
    is_version_label,
    issues_to_label,
    label_release,
    main,
)

CUTOFF = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def issue(number, *, closed_at="2026-11-19T10:00:00Z", reason="completed", **extra):
    data = {
        "number": number,
        "state": "closed",
        "state_reason": reason,
        "closed_at": closed_at,
        "labels": [{"name": "bug"}],
    }
    data.update(extra)
    return data


class FakeTracker:
    def __init__(self, issues):
        self.issues = issues
        self.created: list[str] = []
        self.added: list[tuple[int, str]] = []

    def closed_issues(self):
        return iter(self.issues)

    def ensure_label(self, name):
        self.created.append(name)

    def add_label(self, number, name):
        self.added.append((number, name))


@pytest.mark.parametrize("name", ["0.8.0", "v0.7.2", "10.20.30"])
def test_version_labels(name) -> None:
    assert is_version_label(name)


@pytest.mark.parametrize("name", ["bug", "0.8", "v0.8.0-rc1", "Priority: High"])
def test_other_labels(name) -> None:
    assert not is_version_label(name)


def test_only_done_issues_closed_before_release_get_the_label() -> None:
    issues = [
        issue(1),
        issue(2, reason="not_planned"),
        issue(3, reason="duplicate"),
        issue(4, closed_at="2026-11-20T12:30:00Z"),
        issue(5, pull_request={"url": "..."}),
        issue(6, labels=[{"name": "0.7.0"}]),
        issue(7, labels=["v0.6.0"]),
        issue(8, state="open", closed_at=None, state_reason=None),
        issue(9, closed_at="2026-11-20T12:00:00Z"),
    ]
    assert issues_to_label(issues, CUTOFF) == [1, 9]


def test_label_release_creates_the_label_once() -> None:
    tracker = FakeTracker([issue(3), issue(1), issue(2, reason="not_planned")])
    assert label_release(tracker, "0.8.0", CUTOFF) == [1, 3]
    assert tracker.created == ["0.8.0"]
    assert tracker.added == [(1, "0.8.0"), (3, "0.8.0")]


def test_nothing_to_label_skips_the_label() -> None:
    tracker = FakeTracker([issue(1, labels=[{"name": "0.7.0"}])])
    assert label_release(tracker, "0.8.0", CUTOFF) == []
    assert tracker.created == []


def test_dry_run_changes_nothing(capsys) -> None:
    tracker = FakeTracker([issue(4)])
    argv = ["0.8.0", "--cutoff", "2026-11-20T12:00:00Z", "--dry-run"]
    assert main(argv, tracker=tracker) == 0
    assert tracker.created == tracker.added == []
    assert "#4" in capsys.readouterr().out


def test_cutoff_without_time_zone_is_utc() -> None:
    tracker = FakeTracker([issue(4, closed_at="2026-11-20T11:59:00Z")])
    assert main(["0.8.0", "--cutoff", "2026-11-20T12:00:00"], tracker=tracker) == 0
    assert tracker.added == [(4, "0.8.0")]


def test_version_must_be_plain_number() -> None:
    with pytest.raises(LabelError):
        label_release(FakeTracker([]), "v0.8.0", CUTOFF)


def test_api_must_use_https() -> None:
    with pytest.raises(LabelError):
        GitHubIssues("owner/repo", "token", api_url="file:///etc")


def test_missing_token_is_an_error(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert main(["0.8.0", "--cutoff", "2026-11-20T12:00:00Z"]) == 1
    assert "GH_TOKEN" in capsys.readouterr().err
