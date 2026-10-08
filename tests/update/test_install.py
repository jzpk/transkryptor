"""Testy zastosowania aktualizacji (podmiana AppImage, warunki samoaktualizacji)."""

from __future__ import annotations

import os

import pytest

from transkryptor.errors import UpdateError
from transkryptor.update.install import apply_update, can_self_update


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


def test_appimage_is_replaced_in_place_and_restarted(tmp_path) -> None:
    current = tmp_path / "Transkryptor.AppImage"
    current.write_bytes(b"stara wersja")
    new = tmp_path / "cache" / "Transkryptor-1.0.0-x86_64.AppImage"
    new.parent.mkdir()
    new.write_bytes(b"nowa wersja")
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
