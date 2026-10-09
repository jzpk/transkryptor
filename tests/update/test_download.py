"""Testy pobierania artefaktu z weryfikacją SHA256."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from transkryptor.errors import UpdateError
from transkryptor.update.download import (
    DownloadCancelled,
    clear_downloads,
    download_release,
    parse_checksums,
    verify_downloaded,
)
from transkryptor.update.releases import parse_release
from transkryptor.update.signature import trusted_comment_for

ASSET = "Transkryptor-1.0.0-x86_64.AppImage"


SIGNED_SUMS = ["SHA256SUMS.txt", "SHA256SUMS.txt.minisig"]


def release_from(github):
    return parse_release(github.payload(), "linux")


def names_in(directory) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


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
    assert names_in(tmp_path / "1.0.0") == SIGNED_SUMS


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
    assert names_in(tmp_path / "1.0.0") == SIGNED_SUMS


def test_release_without_platform_artifact_is_an_error(github, tmp_path) -> None:
    github.publish("1.0.0", {"Transkryptor-1.0.0-windows-x64-setup.exe": b"x"})
    with github.client() as client, pytest.raises(UpdateError):
        download_release(release_from(github), client, tmp_path)


def test_signed_checksums_are_kept_next_to_the_artifact(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    with github.client() as client:
        path = download_release(release_from(github), client, tmp_path)
    assert names_in(path.parent) == sorted([ASSET, *SIGNED_SUMS])
    assert verify_downloaded(path) == hashlib.sha256(b"obraz").hexdigest()


def test_release_without_signature_is_not_downloaded(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    release = replace(release_from(github), signature=None)
    with github.client() as client, pytest.raises(UpdateError):
        download_release(release, client, tmp_path)
    assert github.downloads == []


@pytest.mark.parametrize(
    "forgery",
    ["swapped_checksums", "foreign_key", "older_release", "garbage"],
)
def test_bad_signature_rejects_the_release(
    github, tmp_path, forgery, foreign_key
) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    genuine = github.checksums().encode()
    if forgery == "swapped_checksums":
        # Napastnik podmienia artefakt i sumy, ale nie ma klucza: podpis stary.
        github.signature_override = github.signature()
        github.files = {ASSET: b"podrobiony obraz"}
    elif forgery == "foreign_key":
        github.signature_override = foreign_key.sign(
            genuine, trusted_comment_for("1.0.0")
        )
    elif forgery == "older_release":
        # Podpisane sumy starszego wydania podstawione pod nowy tag.
        github.signature_override = github.key.sign(
            genuine, trusted_comment_for("0.9.0")
        )
    else:
        github.signature_override = "śmieci"
    with github.client() as client, pytest.raises(UpdateError) as caught:
        download_release(release_from(github), client, tmp_path)
    assert github.downloads == []
    assert "1.0.0" in caught.value.user_message


def test_without_trusted_keys_nothing_is_downloaded(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    with github.client() as client, pytest.raises(UpdateError):
        download_release(release_from(github), client, tmp_path, trusted_keys=())
    assert github.downloads == []


def test_file_changed_after_download_fails_verification(github, tmp_path) -> None:
    github.publish("1.0.0", {ASSET: b"obraz"})
    with github.client() as client:
        path = download_release(release_from(github), client, tmp_path)
    path.write_bytes(b"podmieniony po pobraniu")
    with pytest.raises(UpdateError):
        verify_downloaded(path)
    assert not path.parent.exists()
