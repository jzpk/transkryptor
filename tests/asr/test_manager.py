"""Testy pobierania modelu: sukces, błąd/ponowienie, anulowanie, kompletność."""

import hashlib
from dataclasses import replace
from functools import partial
from pathlib import Path

import httpx
import pytest

from transkryptor.asr.manager import (
    COMPLETE_MARKER,
    DownloadCancelled,
    ModelManager,
    hf_streaming_download,
    model_file_path,
)
from transkryptor.asr.models import (
    DEFAULT_MODEL,
    REQUIRED_FILES,
    AsrModelInfo,
    ModelFile,
)
from transkryptor.errors import ModelDownloadError


def fake_downloader(
    model: AsrModelInfo, dest: Path, on_progress, should_cancel
) -> None:
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
        def failing_downloader(model, dest, on_progress, should_cancel) -> None:
            (dest / "config.json").write_bytes(b"partial")
            raise ConnectionError("brak sieci")

        manager = ModelManager(models_root=tmp_path, downloader=failing_downloader)
        with pytest.raises(ModelDownloadError) as exc_info:
            manager.download()
        assert exc_info.value.retry_hint
        assert not manager.is_downloaded()

    def test_partial_directory_is_removed_so_retry_starts_clean(self, tmp_path) -> None:
        calls = []

        def flaky_downloader(model, dest, on_progress, should_cancel) -> None:
            calls.append(1)
            if len(calls) == 1:
                (dest / "config.json").write_bytes(b"partial")
                raise ConnectionError("brak sieci")
            fake_downloader(model, dest, on_progress, should_cancel)

        manager = ModelManager(models_root=tmp_path, downloader=flaky_downloader)
        with pytest.raises(ModelDownloadError):
            manager.download()
        assert not manager.model_dir.exists()
        # Ponowienie po błędzie kończy się sukcesem (NFR-03).
        manager.download()
        assert manager.is_downloaded()


class TestCancellation:
    def test_cancel_during_download(self, tmp_path) -> None:
        def cancelling_downloader(model, dest, on_progress, should_cancel) -> None:
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
        def incomplete_downloader(model, dest, on_progress, should_cancel) -> None:
            (dest / "config.json").write_bytes(b"fake")

        manager = ModelManager(models_root=tmp_path, downloader=incomplete_downloader)
        with pytest.raises(ModelDownloadError, match="niekompletny"):
            manager.download()
        assert not manager.is_downloaded()


def small_model(*contents: tuple[str, bytes]) -> AsrModelInfo:
    """Model testowy z przypiętymi sumami podanych treści plików."""
    files = tuple(
        ModelFile(name, len(data), hashlib.sha256(data).hexdigest())
        for name, data in contents
    )
    return replace(
        DEFAULT_MODEL,
        key="test",
        hf_revision="0123abcd" * 5,
        files=files,
        approx_size_bytes=sum(file.size for file in files),
    )


def serving(contents: dict[str, bytes], requested: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        name = request.url.path.rsplit("/", 1)[-1]
        if name not in contents:
            return httpx.Response(404)
        return httpx.Response(200, content=contents[name])

    return httpx.MockTransport(handler)


class TestVerifiedDownload:
    """SEC-02/SEC-05: przypięta rewizja, lista plików i sumy SHA-256."""

    def _manager(self, tmp_path, model, served, requested) -> ModelManager:
        return ModelManager(
            model=model,
            models_root=tmp_path,
            downloader=partial(
                hf_streaming_download, transport=serving(served, requested)
            ),
        )

    def test_downloads_only_listed_files_from_pinned_revision(self, tmp_path) -> None:
        model = small_model(("config.json", b"{}"), ("model.bin", b"wagi"))
        requested: list[str] = []
        served = {"config.json": b"{}", "model.bin": b"wagi", "README.md": b"x"}
        manager = self._manager(tmp_path, model, served, requested)

        manager.download()

        assert manager.is_downloaded()
        assert requested == [
            f"/{model.hf_repo_id}/resolve/{model.hf_revision}/config.json",
            f"/{model.hf_repo_id}/resolve/{model.hf_revision}/model.bin",
        ]
        assert sorted(p.name for p in manager.model_dir.iterdir()) == [
            COMPLETE_MARKER,
            "config.json",
            "model.bin",
        ]
        marker = (manager.model_dir / COMPLETE_MARKER).read_text(encoding="utf-8")
        assert marker == f"{model.hf_repo_id}@{model.hf_revision}"

    def test_checksum_mismatch_leaves_no_model(self, tmp_path) -> None:
        model = small_model(("config.json", b"{}"), ("model.bin", b"wagi"))
        served = {"config.json": b"{}", "model.bin": b"podmienione wagi"}
        manager = self._manager(tmp_path, model, served, [])

        with pytest.raises(ModelDownloadError, match="model.bin") as exc_info:
            manager.download()

        assert exc_info.value.retry_hint
        assert not manager.is_downloaded()
        assert not manager.model_dir.exists()

    def test_same_size_different_content_is_rejected(self, tmp_path) -> None:
        model = small_model(("model.bin", b"wagi"))
        manager = self._manager(tmp_path, model, {"model.bin": b"WAGI"}, [])
        with pytest.raises(ModelDownloadError):
            manager.download()
        assert not manager.model_dir.exists()

    def test_name_outside_model_dir_is_rejected(self, tmp_path) -> None:
        model = small_model(("../ucieczka.txt", b"x"))
        manager = self._manager(tmp_path, model, {"ucieczka.txt": b"x"}, [])
        with pytest.raises(ModelDownloadError):
            manager.download()
        assert not (tmp_path / "ucieczka.txt").exists()

    @pytest.mark.parametrize("name", ["../x", "/etc/passwd", "a/../../x", "."])
    def test_model_file_path_rejects_escaping_names(self, tmp_path, name) -> None:
        with pytest.raises(ModelDownloadError):
            model_file_path(tmp_path, name)

    def test_model_file_path_accepts_nested_names(self, tmp_path) -> None:
        assert model_file_path(tmp_path, "sub/model.bin") == (
            tmp_path.resolve() / "sub" / "model.bin"
        )


def test_default_model_pins_revision_and_hashes() -> None:
    assert len(DEFAULT_MODEL.hf_revision) == 40
    assert {file.name for file in DEFAULT_MODEL.files} == set(REQUIRED_FILES)
    assert all(len(file.sha256) == 64 for file in DEFAULT_MODEL.files)
