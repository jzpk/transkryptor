"""Testy etykiet zgłoszeń: wersja programu albo wdrożenie strony."""

from datetime import UTC, datetime

import pytest

from transkryptor.packaging.issue_labels import (
    DEPLOYED_LABEL,
    SITE_TARGET,
    GitHubIssues,
    LabelError,
    is_version_label,
    issues_to_label,
    label_issues,
    main,
    referenced_issues,
    release_target,
)

CUTOFF = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
RELEASE = release_target("0.8.0")


def issue(
    number, *labels, closed_at="2026-11-19T10:00:00Z", reason="completed", **extra
):
    data = {
        "number": number,
        "state": "closed",
        "state_reason": reason,
        "closed_at": closed_at,
        "labels": [{"name": name} for name in labels or ("bug",)],
    }
    data.update(extra)
    return data


class FakeTracker:
    def __init__(self, issues):
        self.issues = issues
        self.created: list[tuple[str, str]] = []
        self.added: list[tuple[int, str]] = []

    def closed_issues(self):
        return iter(self.issues)

    def issue(self, number):
        return next((item for item in self.issues if item["number"] == number), None)

    def ensure_label(self, name, description):
        self.created.append((name, description))

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
        issue(6, "bug", "0.7.0"),
        issue(7, labels=["v0.6.0"]),
        issue(8, state="open", closed_at=None, state_reason=None),
        issue(9, closed_at="2026-11-20T12:00:00Z"),
    ]
    assert issues_to_label(issues, RELEASE, CUTOFF) == [1, 9]


def test_release_skips_webpage_issues_and_site_takes_only_them() -> None:
    issues = [
        issue(1, "bug"),
        issue(2, "bug", "webpage"),
        issue(3, "enhancement", "Webpage"),
        issue(4, "webpage", DEPLOYED_LABEL),
        issue(5, "webpage", reason="not_planned"),
    ]
    assert issues_to_label(issues, RELEASE, CUTOFF) == [1]
    assert issues_to_label(issues, SITE_TARGET, CUTOFF) == [2, 3]


def test_label_issues_creates_the_label_once() -> None:
    tracker = FakeTracker([issue(3), issue(1), issue(2, reason="not_planned")])
    assert label_issues(tracker, RELEASE, CUTOFF) == [1, 3]
    assert tracker.created == [("0.8.0", RELEASE.description)]
    assert tracker.added == [(1, "0.8.0"), (3, "0.8.0")]


def test_nothing_to_label_skips_the_label() -> None:
    tracker = FakeTracker([issue(1, "bug", "0.7.0")])
    assert label_issues(tracker, RELEASE, CUTOFF) == []
    assert tracker.created == []


def test_site_mode_labels_deployed_webpage_issues(capsys) -> None:
    tracker = FakeTracker([issue(1), issue(2, "webpage")])
    assert main(["site", "--cutoff", "2026-11-20T12:00:00Z"], tracker=tracker) == 0
    assert tracker.added == [(2, DEPLOYED_LABEL)]
    assert f"etykietą {DEPLOYED_LABEL}: #2" in capsys.readouterr().out


def test_dry_run_changes_nothing(capsys) -> None:
    tracker = FakeTracker([issue(4)])
    argv = ["release", "0.8.0", "--cutoff", "2026-11-20T12:00:00Z", "--dry-run"]
    assert main(argv, tracker=tracker) == 0
    assert tracker.created == tracker.added == []
    assert "#4" in capsys.readouterr().out


def test_cutoff_without_time_zone_is_utc() -> None:
    tracker = FakeTracker([issue(4, closed_at="2026-11-20T11:59:00Z")])
    argv = ["release", "0.8.0", "--cutoff", "2026-11-20T12:00:00"]
    assert main(argv, tracker=tracker) == 0
    assert tracker.added == [(4, "0.8.0")]


def test_version_must_be_plain_number() -> None:
    with pytest.raises(LabelError):
        release_target("v0.8.0")


def test_api_must_use_https() -> None:
    with pytest.raises(LabelError):
        GitHubIssues("owner/repo", "token", api_url="file:///etc")


def test_missing_token_is_an_error(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert main(["site", "--cutoff", "2026-11-20T12:00:00Z"]) == 1
    assert "GH_TOKEN" in capsys.readouterr().err


def test_deployed_label_is_matched_regardless_of_case() -> None:
    """GitHub nie rozróżnia wielkości liter w etykietach - ponowne wdrożenie
    nie oznacza drugi raz zgłoszenia z etykietą ``deployed``."""
    assert not SITE_TARGET.applies_to(["webpage", DEPLOYED_LABEL.lower()])
    assert not SITE_TARGET.applies_to(["Webpage", DEPLOYED_LABEL])
    assert SITE_TARGET.applies_to(["webpage"])


def test_closing_references_are_read_from_commit_messages() -> None:
    messages = (
        "fix: keep the panel visible\n\nCloses #57\n\n"
        "feat: add a thing (#61)\n\nFixes: #12, resolves #3 and closed #57\n"
        "see #99, prefix#5\n"
    )
    assert referenced_issues(messages) == [3, 12, 57]


def test_patch_release_labels_only_issues_named_in_its_commits(tmp_path) -> None:
    tracker = FakeTracker(
        [
            issue(1, state="open", closed_at=None, reason=None),  # zamknie scalenie
            issue(2),
            issue(3, "0.8.1"),  # już wydane
            issue(4, "webpage"),
            issue(5, reason="not_planned"),
            issue(6, pull_request={"url": "x"}),
            issue(7),  # zrobione tylko na main - brak w commitach
        ]
    )
    messages = tmp_path / "commits.txt"
    messages.write_text(
        "Closes #1\nCloses #2\nCloses #3\nCloses #4\nCloses #5\nCloses #6\n"
        "Closes #404\n",
        encoding="utf-8",
    )
    assert main(["release", "0.8.2", "--messages", str(messages)], tracker) == 0
    assert tracker.added == [(1, "0.8.2"), (2, "0.8.2")]


def test_release_needs_cutoff_or_messages() -> None:
    with pytest.raises(SystemExit):
        main(["release", "0.8.2"], FakeTracker([]))
    with pytest.raises(SystemExit):
        main(
            ["release", "0.8.2", "--cutoff", "2026-11-20", "--messages", "x"],
            FakeTracker([]),
        )
