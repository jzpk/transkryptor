"""Testy pobierania modelu: sukces, błąd/ponowienie, anulowanie, kompletność."""

from pathlib import Path

import pytest

from transkryptor.asr.manager import (
    COMPLETE_MARKER,
    DownloadCancelled,
    ModelManager,
)
from transkryptor.asr.models import REQUIRED_FILES
from transkryptor.errors import ModelDownloadError


def fake_downloader(repo_id: str, dest: Path, on_progress, should_cancel) -> None:
    """Imitacja pobierania: tworzy wymagane pliki i raportuje postęp."""
    for name in REQUIRED_FILES:
        (dest / name).write_bytes(b"fake")
        on_progress(1024, 4096, name)


@pytest.fixture
def manager(tmp_path) -> ModelManager:
    return ModelManager(models_root=tmp_path, downloader=fake_downloader)


class TestInitialState:
    def test_model_is_missing_initially(self, manager) -> None:
        """Brak modelu jest stanem normalnym, nie awarią."""
        assert not manager.is_downloaded()
        assert set(manager.missing_files()) == set(REQUIRED_FILES)


class TestSuccessfulDownload:
    def test_download_marks_model_ready(self, manager) -> None:
        dest = manager.download()
        assert dest == manager.model_dir
        assert manager.is_downloaded()
        assert (dest / COMPLETE_MARKER).is_file()
        assert manager.missing_files() == []

    def test_progress_is_reported(self, manager) -> None:
        events: list[tuple[int, int | None, str]] = []
        manager.download(
            on_progress=lambda done, total, name: events.append((done, total, name))
        )
        assert len(events) == len(REQUIRED_FILES)
        assert all(total == 4096 for _done, total, _name in events)


class TestDownloadErrorAndRetry:
    def test_error_raises_model_download_error_with_retry_hint(self, tmp_path) -> None:
        def failing_downloader(repo_id, dest, on_progress, should_cancel) -> None:
            (dest / "config.json").write_bytes(b"partial")
            raise ConnectionError("brak sieci")

        manager = ModelManager(models_root=tmp_path, downloader=failing_downloader)
        with pytest.raises(ModelDownloadError) as exc_info:
            manager.download()
        assert exc_info.value.retry_hint
        assert not manager.is_downloaded()

    def test_partial_directory_is_removed_so_retry_starts_clean(self, tmp_path) -> None:
        calls = []

        def flaky_downloader(repo_id, dest, on_progress, should_cancel) -> None:
            calls.append(1)
            if len(calls) == 1:
                (dest / "config.json").write_bytes(b"partial")
                raise ConnectionError("brak sieci")
            fake_downloader(repo_id, dest, on_progress, should_cancel)

        manager = ModelManager(models_root=tmp_path, downloader=flaky_downloader)
        with pytest.raises(ModelDownloadError):
            manager.download()
        assert not manager.model_dir.exists()
        # Ponowienie po błędzie kończy się sukcesem (NFR-03).
        manager.download()
        assert manager.is_downloaded()


class TestCancellation:
    def test_cancel_during_download(self, tmp_path) -> None:
        def cancelling_downloader(repo_id, dest, on_progress, should_cancel) -> None:
            (dest / "config.json").write_bytes(b"partial")
            if should_cancel():
                raise DownloadCancelled()

        manager = ModelManager(models_root=tmp_path, downloader=cancelling_downloader)
        with pytest.raises(DownloadCancelled):
            manager.download(should_cancel=lambda: True)
        assert not manager.is_downloaded()
        assert not manager.model_dir.exists()


class TestIncompleteResult:
    def test_missing_files_after_download_raise_error(self, tmp_path) -> None:
        def incomplete_downloader(repo_id, dest, on_progress, should_cancel) -> None:
            (dest / "config.json").write_bytes(b"fake")

        manager = ModelManager(models_root=tmp_path, downloader=incomplete_downloader)
        with pytest.raises(ModelDownloadError, match="niekompletny"):
            manager.download()
        assert not manager.is_downloaded()
