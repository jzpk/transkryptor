"""Testy przebiegu „sprawdź → pobierz”."""

from __future__ import annotations

import pytest

from transkryptor.update.service import UpdateService, UpdateStage, UpdateStatus

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
        )

    return make


def test_newer_release_is_downloaded(github, make_service, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service().run()
    assert outcome.status is UpdateStatus.READY
    assert outcome.artifact == tmp_path / "updates" / "1.0.0" / ASSET
    assert outcome.release is not None and outcome.release.version == "1.0.0"


def test_stages_and_progress_reach_the_caller(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    stages: list[tuple[UpdateStage, str | None]] = []
    progress: list[tuple[int, int | None]] = []
    outcome = make_service().run(
        on_progress=lambda done, total: progress.append((done, total)),
        on_stage=lambda stage, release: stages.append(
            (stage, release.version if release else None)
        ),
    )
    assert outcome.status is UpdateStatus.READY
    assert stages == [(UpdateStage.CHECKING, None), (UpdateStage.DOWNLOADING, "1.0.0")]
    assert progress[-1] == (5, 5)


def test_up_to_date_check_has_no_download_stage(github, make_service) -> None:
    github.publish("0.2.0", {ASSET: b"obraz"})
    stages: list[UpdateStage] = []
    make_service().run(on_stage=lambda stage, _release: stages.append(stage))
    assert stages == [UpdateStage.CHECKING]


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


def test_every_run_checks_without_a_daily_limit(github, make_service) -> None:
    """Sprawdzenie nie korzysta z API GitHuba, więc nie ma dziennego limitu."""
    github.publish("0.2.0", {ASSET: b"obraz"})
    for _ in range(20):
        assert make_service().run().status is UpdateStatus.UP_TO_DATE
    github.publish("1.0.0", {ASSET: b"obraz"})
    assert make_service().run().status is UpdateStatus.READY
    assert github.latest_calls == 21


def test_offline_is_reported(github, make_service) -> None:
    github.offline = True
    assert make_service().run().status is UpdateStatus.OFFLINE


def test_failed_download_is_retried_on_the_next_run(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    github.checksums_override = f"{'0' * 64}  {ASSET}\n"
    failed = make_service().run()
    assert failed.status is UpdateStatus.ERROR
    assert failed.release is not None and failed.release.version == "1.0.0"

    github.checksums_override = None
    assert make_service().run().status is UpdateStatus.READY


def test_no_release_yet_is_up_to_date(github, make_service) -> None:
    github.latest_status = 404
    outcome = make_service().run()
    assert outcome.status is UpdateStatus.UP_TO_DATE
    assert outcome.release is None


def test_server_error_is_reported(github, make_service) -> None:
    github.latest_status = 500
    outcome = make_service().run()
    assert outcome.status is UpdateStatus.ERROR
    assert outcome.error is not None


def test_closing_the_app_cancels_the_download(github, make_service) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    outcome = make_service().run(should_cancel=lambda: True)
    assert outcome.status is UpdateStatus.CANCELLED
