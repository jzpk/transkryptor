"""Testy zastosowania aktualizacji (podmiana AppImage, warunki samoaktualizacji)."""

from __future__ import annotations

import hashlib
import os
import sys

import pytest

from transkryptor.errors import UpdateError
from transkryptor.update import install
from transkryptor.update.install import apply_update, can_self_update
from transkryptor.update.signature import trusted_comment_for

NEW_IMAGE = "Transkryptor-1.0.0-x86_64.AppImage"


def downloaded(tmp_path, release_key, data: bytes = b"nowa wersja"):
    """Pobrana aktualizacja: artefakt i podpisane sumy w katalogu wersji."""
    directory = tmp_path / "cache" / "1.0.0"
    directory.mkdir(parents=True)
    artifact = directory / NEW_IMAGE
    artifact.write_bytes(data)
    sums = f"{hashlib.sha256(data).hexdigest()}  {NEW_IMAGE}\n".encode()
    (directory / "SHA256SUMS.txt").write_bytes(sums)
    (directory / "SHA256SUMS.txt.minisig").write_text(
        release_key.sign(sums, trusted_comment_for("1.0.0")), encoding="utf-8"
    )
    return artifact


def test_development_environment_never_self_updates(tmp_path) -> None:
    image = tmp_path / "Transkryptor.AppImage"
    image.write_bytes(b"x")
    env = {"APPIMAGE": str(image)}
    assert not can_self_update(platform="linux", frozen=False, environ=env)
    assert not can_self_update(platform="win32", frozen=False, environ={})


def test_windows_artifact_self_updates() -> None:
    assert can_self_update(platform="win32", frozen=True, environ={})


def test_linux_requires_a_writable_appimage(tmp_path) -> None:
    image = tmp_path / "Transkryptor.AppImage"
    assert not can_self_update(platform="linux", frozen=True, environ={})
    env = {"APPIMAGE": str(image)}
    assert not can_self_update(platform="linux", frozen=True, environ=env)
    image.write_bytes(b"x")
    assert can_self_update(platform="linux", frozen=True, environ=env)


def test_unsupported_platform_does_not_self_update() -> None:
    assert not can_self_update(platform="darwin", frozen=True, environ={})


def test_appimage_is_replaced_in_place_and_restarted(tmp_path, release_key) -> None:
    current = tmp_path / "Transkryptor.AppImage"
    current.write_bytes(b"stara wersja")
    new = downloaded(tmp_path, release_key)
    launched: list[list[str]] = []

    apply_update(
        new,
        platform="linux",
        environ={"APPIMAGE": str(current)},
        launcher=lambda command: launched.append(list(command)),
    )

    assert current.read_bytes() == b"nowa wersja"
    assert os.access(current, os.X_OK)
    assert not new.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Transkryptor.AppImage",
        "cache",
    ]
    assert launched == [[str(current)]]


def test_linux_without_appimage_cannot_apply(tmp_path) -> None:
    with pytest.raises(UpdateError):
        apply_update(tmp_path / "x", platform="linux", environ={})


def test_failed_replacement_keeps_the_current_image(tmp_path) -> None:
    current = tmp_path / "Transkryptor.AppImage"
    current.write_bytes(b"stara wersja")
    with pytest.raises(UpdateError):
        apply_update(
            tmp_path / "brak.AppImage",
            platform="linux",
            environ={"APPIMAGE": str(current)},
            launcher=lambda _command: pytest.fail("restart po nieudanej podmianie"),
        )
    assert current.read_bytes() == b"stara wersja"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Transkryptor.AppImage"]


def test_file_replaced_after_download_is_not_installed(tmp_path, release_key) -> None:
    current = tmp_path / "Transkryptor.AppImage"
    current.write_bytes(b"stara wersja")
    new = downloaded(tmp_path, release_key)
    new.write_bytes(b"podmieniony plik")
    with pytest.raises(UpdateError):
        apply_update(
            new,
            platform="linux",
            environ={"APPIMAGE": str(current)},
            launcher=lambda _command: pytest.fail("uruchomiono podmieniony plik"),
        )
    assert current.read_bytes() == b"stara wersja"
    assert not (tmp_path / "cache" / "1.0.0").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Transkryptor.AppImage",
        "cache",
    ]


def test_windows_installer_is_verified_before_launch(tmp_path, release_key) -> None:
    new = downloaded(tmp_path, release_key)
    (new.parent / "SHA256SUMS.txt.minisig").write_text("śmieci", encoding="utf-8")
    with pytest.raises(UpdateError) as caught:
        apply_update(new, platform="win32")
    assert "1.0.0" in caught.value.user_message


windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="blokada pliku instalatora tylko na Windows"
)


@windows_only
def test_installer_cannot_be_replaced_between_verification_and_launch(
    tmp_path, release_key, monkeypatch
) -> None:
    new = downloaded(tmp_path, release_key)
    swapped = tmp_path / "podmiana.exe"
    swapped.write_bytes(b"obcy instalator")
    launched = []

    def run_installer(installer) -> None:
        with pytest.raises(PermissionError):
            installer.write_bytes(b"obcy instalator")
        with pytest.raises(PermissionError):
            os.replace(swapped, installer)
        with pytest.raises(PermissionError):
            installer.unlink()
        assert installer.read_bytes() == b"nowa wersja"
        launched.append(installer)

    monkeypatch.setattr(install, "_run_windows_installer", run_installer)
    try:
        apply_update(new, platform="win32")
        assert launched == [new]
        # Instalator czyta swój plik także po starcie - blokada trwa dalej.
        with pytest.raises(PermissionError):
            new.write_bytes(b"obcy instalator")
    finally:
        install.release_launch_locks()
    new.write_bytes(b"po zwolnieniu blokady")


@windows_only
def test_failed_launch_releases_the_installer_lock(
    tmp_path, release_key, monkeypatch
) -> None:
    new = downloaded(tmp_path, release_key)

    def run_installer(_installer) -> None:
        raise UpdateError(user_message="odmowa UAC")

    monkeypatch.setattr(install, "_run_windows_installer", run_installer)
    with pytest.raises(UpdateError):
        apply_update(new, platform="win32")
    new.write_bytes(b"po zwolnieniu blokady")


def test_installer_lock_is_windows_only(tmp_path) -> None:
    if sys.platform == "win32":
        pytest.skip("sprawdza zachowanie poza Windows")
    target = tmp_path / "setup.exe"
    target.write_bytes(b"instalator")
    assert install._lock_for_launch(target) is None
