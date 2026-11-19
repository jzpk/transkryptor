"""Testy sprawdzenia i pobrania aktualizacji."""

from __future__ import annotations

import pytest

from transkryptor.update.advisory import AdvisoryStore
from transkryptor.update.service import UpdateService, UpdateStatus

ASSET = "Transkryptor-1.0.0-x86_64.AppImage"


@pytest.fixture
def make_service(tmp_path, client_factory):
    def make(*, current: str = "0.2.0", self_update: bool = True) -> UpdateService:
        return UpdateService(
            current_version=current,
            download_root=tmp_path / "updates",
            client_factory=client_factory,
            platform="linux",
            self_update=self_update,
            advisory_store=AdvisoryStore(tmp_path / "advisory"),
        )

    return make


def test_check_offers_newer_release_without_downloading(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service().check()
    assert outcome.status is UpdateStatus.DOWNLOADABLE
    assert outcome.release is not None and outcome.release.version == "1.0.0"
    assert outcome.artifact is None
    assert github.downloads == []


def test_download_fetches_the_offered_release(github, make_service, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    service = make_service()
    release = service.check().release
    assert release is not None
    progress: list[tuple[int, int | None]] = []
    outcome = service.download(
        release, on_progress=lambda done, total: progress.append((done, total))
    )
    assert outcome.status is UpdateStatus.READY
    assert outcome.artifact == tmp_path / "updates" / "1.0.0" / ASSET
    assert progress[-1] == (5, 5)


def test_current_version_is_up_to_date(github, make_service, tmp_path) -> None:
    (tmp_path / "updates" / "0.9.0").mkdir(parents=True)
    github.publish("0.2.0", {ASSET: b"obraz"})
    outcome = make_service().check()
    assert outcome.status is UpdateStatus.UP_TO_DATE
    assert github.downloads == []
    assert list((tmp_path / "updates").iterdir()) == []


def test_development_mode_only_reports_new_version(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service(self_update=False).check()
    assert outcome.status is UpdateStatus.AVAILABLE
    assert github.downloads == []


def test_every_run_checks_without_a_daily_limit(github, make_service) -> None:
    """Sprawdzenie nie korzysta z API GitHuba, więc nie ma dziennego limitu."""
    github.publish("0.2.0", {ASSET: b"obraz"})
    for _ in range(20):
        assert make_service().check().status is UpdateStatus.UP_TO_DATE
    github.publish("1.0.0", {ASSET: b"obraz"})
    assert make_service().check().status is UpdateStatus.DOWNLOADABLE
    assert github.latest_calls == 21


def test_offline_is_reported(github, make_service) -> None:
    github.offline = True
    assert make_service().check().status is UpdateStatus.OFFLINE


def test_offline_download_is_reported(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    service = make_service()
    release = service.check().release
    assert release is not None
    github.offline = True
    assert service.download(release).status is UpdateStatus.OFFLINE


def test_failed_download_can_be_retried(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    service = make_service()
    release = service.check().release
    assert release is not None
    github.checksums_override = f"{'0' * 64}  {ASSET}\n"
    failed = service.download(release)
    assert failed.status is UpdateStatus.ERROR
    assert failed.release is not None and failed.release.version == "1.0.0"

    github.checksums_override = None
    assert service.download(release).status is UpdateStatus.READY


def test_no_release_yet_is_up_to_date(github, make_service) -> None:
    github.latest_status = 404
    outcome = make_service().check()
    assert outcome.status is UpdateStatus.UP_TO_DATE
    assert outcome.release is None


def test_server_error_is_reported(github, make_service) -> None:
    github.latest_status = 500
    outcome = make_service().check()
    assert outcome.status is UpdateStatus.ERROR
    assert outcome.error is not None


def test_closing_the_app_cancels_the_download(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    service = make_service()
    release = service.check().release
    assert release is not None
    outcome = service.download(release, should_cancel=lambda: True)
    assert outcome.status is UpdateStatus.CANCELLED


def test_advisory_for_the_current_version_is_reported(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    github.publish_advisory(1, "1.0.0", {"pl": "Luka."})
    outcome = make_service(current="0.2.0").check()
    assert outcome.status is UpdateStatus.DOWNLOADABLE
    assert outcome.advisory is not None and outcome.advisory.message("pl") == "Luka."
    assert github.downloads == []


def test_advisory_for_older_versions_is_not_reported(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    github.publish_advisory(1, "0.2.0")
    assert make_service(current="0.2.0").check().advisory is None


def test_stored_advisory_is_reported_offline(github, make_service) -> None:
    github.publish("0.2.0", {ASSET: b"obraz"})
    github.publish_advisory(1, "1.0.0")
    assert make_service().check().advisory is not None
    github.offline = True
    outcome = make_service().check()
    assert outcome.status is UpdateStatus.OFFLINE
    assert outcome.advisory is not None


def test_broken_advisory_does_not_break_the_check(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    github.advisory_files = {"advisory.json": b"{}", "advisory.json.minisig": b"x"}
    outcome = make_service().check()
    assert outcome.status is UpdateStatus.DOWNLOADABLE
    assert outcome.advisory is None
