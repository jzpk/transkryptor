"""Testy pobierania artefaktu z weryfikacją SHA256."""

from __future__ import annotations

import pytest

from transkryptor.errors import UpdateError
from transkryptor.update.download import (
    DownloadCancelled,
    clear_downloads,
    download_release,
    parse_checksums,
)
from transkryptor.update.releases import parse_release

ASSET = "Transkryptor-1.0.0-x86_64.AppImage"


def release_from(github):
    return parse_release(github.payload(), "linux")


def test_parse_checksums_accepts_sha256sum_format() -> None:
    text = "ABC  plik.exe\ndef *obraz.AppImage\n\nśmieci\n"
    assert parse_checksums(text) == {"plik.exe": "abc", "obraz.AppImage": "def"}


def test_download_verifies_and_stores_the_artifact(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"nowy obraz"})
    with github.client() as client:
        path = download_release(release_from(github), client, tmp_path)
    assert path == tmp_path / "1.0.0" / ASSET
    assert path.read_bytes() == b"nowy obraz"
    assert not list(path.parent.glob("*.part"))


def test_checksum_mismatch_rejects_the_file(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"nowy obraz"})
    github.checksums_override = f"{'0' * 64}  {ASSET}\n"
    with github.client() as client, pytest.raises(UpdateError):
        download_release(release_from(github), client, tmp_path)
    assert not any((tmp_path / "1.0.0").iterdir())


def test_missing_checksum_entry_is_an_error(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"x"})
    github.checksums_override = ""
    with github.client() as client, pytest.raises(UpdateError):
        download_release(release_from(github), client, tmp_path)
    assert github.downloads == []


def test_verified_file_is_not_downloaded_again(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    with github.client() as client:
        download_release(release_from(github), client, tmp_path)
        download_release(release_from(github), client, tmp_path)
    assert github.downloads == [ASSET]


def test_older_downloads_are_removed(github, tmp_path) -> None:
    (tmp_path / "0.9.0").mkdir()
    (tmp_path / "0.9.0" / "stary.AppImage").write_bytes(b"x")
    github.publish("1.0.0", {ASSET: b"obraz"})
    with github.client() as client:
        download_release(release_from(github), client, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["1.0.0"]

    clear_downloads(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelled_download_leaves_no_partial_file(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    with github.client() as client, pytest.raises(DownloadCancelled):
        download_release(release_from(github), client, tmp_path, lambda: True)
    assert not any((tmp_path / "1.0.0").iterdir())


def test_release_without_platform_artifact_is_an_error(github, tmp_path) -> None:
    github.publish("1.0.0", {"Transkryptor-1.0.0-windows-x64-setup.exe": b"x"})
    with github.client() as client, pytest.raises(UpdateError):
        download_release(release_from(github), client, tmp_path)
