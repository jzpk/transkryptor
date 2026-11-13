"""Testy reguł gałęzi wydań: skąd wolno wydać którą wersję."""

import pytest

from transkryptor.packaging import branches
from transkryptor.packaging.branches import BranchError


@pytest.mark.parametrize(
    ("ref", "bump", "exists"),
    [
        ("release/0.8", "patch", True),
        ("main", "minor", True),
        ("main", "major", False),
        ("main", "patch", False),  # przed założeniem release/0.8
    ],
)
def test_allowed_releases(ref, bump, exists) -> None:
    branches.check(ref, bump, "0.8.1", release_branch_exists=exists)


@pytest.mark.parametrize(
    ("ref", "bump", "message"),
    [
        ("release/0.8", "minor", "tylko wydania patch"),
        ("release/0.7", "patch", "nie zgadza się"),
        ("main", "patch", "release/0.8"),
        ("feature/x", "patch", "wybrano: feature/x"),
        ("release/0.8.1", "patch", "wybrano"),
    ],
)
def test_refused_releases(ref, bump, message) -> None:
    with pytest.raises(BranchError, match=message):
        branches.check(ref, bump, "0.8.1", release_branch_exists=True)


def test_release_branch_of_a_version() -> None:
    assert branches.release_branch("0.8.1") == "release/0.8"
    assert branches.release_branch("v1.10.0") == "release/1.10"


def test_patch_of_an_older_series_is_not_latest() -> None:
    tags = ["v0.8.1", "v0.8.2", "v0.9.0", "v0.10.0", "nightly"]
    assert not branches.is_latest("0.8.3", tags)
    assert not branches.is_latest("0.9.1", tags)
    assert branches.is_latest("0.10.0", tags)  # własny tag już istnieje
    assert branches.is_latest("0.10.1", tags)
    assert branches.is_latest("0.1.0", [])


def test_cli(capsys) -> None:
    assert branches.main(["latest", "0.8.3", "v0.9.0"]) == 0
    assert branches.main(["series", "0.8.3"]) == 0
    assert capsys.readouterr().out.split() == ["false", "release/0.8"]
    args = ["check", "--ref", "main", "--bump", "patch", "--version", "0.8.1"]
    assert branches.main(args) == 0
    assert branches.main([*args, "--release-branch-exists"]) == 1
    assert "::error::" in capsys.readouterr().err
