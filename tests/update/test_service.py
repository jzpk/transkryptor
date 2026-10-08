"""Testy przebiegu „sprawdź → pobierz” z limitem zapytań."""

from __future__ import annotations

from datetime import date

import pytest

from transkryptor.update.quota import RequestQuota
from transkryptor.update.service import UpdateService, UpdateStatus

ASSET = "Transkryptor-1.0.0-x86_64.AppImage"
TODAY = date(2026, 10, 8)


@pytest.fixture
def make_service(tmp_path, client_factory):
    def make(*, current: str = "0.2.0", self_update: bool = True) -> UpdateService:
        return UpdateService(
            current_version=current,
            quota=RequestQuota(tmp_path / "state.json"),
            download_root=tmp_path / "updates",
            client_factory=client_factory,
            platform="linux",
            self_update=self_update,
            today=lambda: TODAY,
        )

    return make


def test_newer_release_is_downloaded(github, make_service, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service().run()
    assert outcome.status is UpdateStatus.READY
    assert outcome.artifact == tmp_path / "updates" / "1.0.0" / ASSET
    assert outcome.release is not None and outcome.release.version == "1.0.0"


def test_current_version_is_up_to_date(github, make_service, tmp_path) -> None:
    (tmp_path / "updates" / "0.9.0").mkdir(parents=True)
    github.publish("0.2.0", {ASSET: b"obraz"})
    outcome = make_service().run()
    assert outcome.status is UpdateStatus.UP_TO_DATE
    assert github.downloads == []
    assert list((tmp_path / "updates").iterdir()) == []


def test_development_mode_only_reports_new_version(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service(self_update=False).run()
    assert outcome.status is UpdateStatus.AVAILABLE
    assert github.downloads == []


def test_at_most_two_api_requests_per_day(github, make_service) -> None:
    github.publish("0.2.0", {ASSET: b"obraz"})
    assert make_service().run().status is UpdateStatus.UP_TO_DATE
    assert make_service().run().status is UpdateStatus.UP_TO_DATE
    assert make_service().run().status is UpdateStatus.QUOTA_EXHAUSTED
    assert github.api_calls == 2


def test_offline_does_not_consume_the_limit(github, make_service) -> None:
    github.offline = True
    for _ in range(3):
        assert make_service().run().status is UpdateStatus.OFFLINE
    github.offline = False
    github.publish("0.2.0", {ASSET: b"obraz"})
    assert make_service().run().status is UpdateStatus.UP_TO_DATE
    assert make_service().run().status is UpdateStatus.UP_TO_DATE
    assert make_service().run().status is UpdateStatus.QUOTA_EXHAUSTED


def test_failed_download_is_retried_without_another_api_call(
    github, make_service
) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    github.checksums_override = f"{'0' * 64}  {ASSET}\n"
    failed = make_service().run()
    assert failed.status is UpdateStatus.ERROR
    assert failed.release is not None and failed.release.version == "1.0.0"

    github.checksums_override = None
    for _ in range(3):
        assert make_service().run().status is UpdateStatus.READY
    assert github.api_calls == 1


def test_api_error_is_reported(github, make_service) -> None:
    github.api_status = 500
    outcome = make_service().run()
    assert outcome.status is UpdateStatus.ERROR
    assert outcome.error is not None


def test_closing_the_app_cancels_the_download(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service().run(should_cancel=lambda: True)
    assert outcome.status is UpdateStatus.CANCELLED
