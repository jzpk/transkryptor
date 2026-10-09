"""Testy zapytania o najnowsze wydanie i porównania wersji."""

from __future__ import annotations

import pytest

from transkryptor.errors import UpdateError
from transkryptor.packaging.metadata import targets
from transkryptor.update import releases
from transkryptor.update.releases import (
    ReleaseInfo,
    fetch_latest,
    is_newer,
    parse_release,
    parse_version,
)

LINUX_ASSET = "Transkryptor-1.2.3-x86_64.AppImage"
WINDOWS_ASSET = "Transkryptor-1.2.3-windows-x64-setup.exe"
DOWNLOADS = "https://github.com/jzpk/transkryptor/releases/download/v1.2.3"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.2.3", (1, 2, 3)),
        ("v0.10.0", (0, 10, 0)),
        (" v2.0.1 ", (2, 0, 1)),
        ("1.2", None),
        ("1.2.3-rc1", None),
        ("wersja", None),
    ],
)
def test_parse_version(text, expected) -> None:
    assert parse_version(text) == expected


def test_is_newer_compares_numerically() -> None:
    assert is_newer("0.10.0", "0.9.9")
    assert is_newer("1.0.0", "0.99.99")
    assert not is_newer("0.2.0", "0.2.0")
    assert not is_newer("0.1.9", "0.2.0")
    assert not is_newer("niepoprawna", "0.2.0")


def test_asset_suffixes_match_release_artifact_names() -> None:
    """Nazwy z narzędzia wydania muszą pasować do wzorców aktualizacji."""
    for key, target in targets("1.2.3").items():
        assert target.artifact_name.endswith(releases.ASSET_SUFFIXES[key])


def payload(*names: str) -> dict:
    return {
        "tag_name": "v1.2.3",
        "html_url": "https://github.com/jzpk/transkryptor/releases/tag/v1.2.3",
        "assets": [
            {"name": n, "browser_download_url": f"{DOWNLOADS}/{n}", "size": 10}
            for n in names
        ],
    }


@pytest.mark.parametrize(
    ("platform", "expected"), [("linux", LINUX_ASSET), ("windows", WINDOWS_ASSET)]
)
def test_parse_release_picks_the_platform_artifact(platform, expected) -> None:
    release = parse_release(
        payload(LINUX_ASSET, WINDOWS_ASSET, "SHA256SUMS.txt"), platform
    )
    assert release.version == "1.2.3"
    assert release.artifact is not None
    assert release.artifact.name == expected
    assert release.checksums is not None
    assert release.checksums.name == "SHA256SUMS.txt"


def test_parse_release_without_platform_artifact() -> None:
    release = parse_release(payload(WINDOWS_ASSET), "linux")
    assert release.artifact is None
    assert release.checksums is None


def test_parse_release_rejects_unversioned_tag() -> None:
    with pytest.raises(UpdateError):
        parse_release({"tag_name": "nightly", "assets": []}, "linux")


def test_release_round_trips_through_dict() -> None:
    release = parse_release(payload(LINUX_ASSET, "SHA256SUMS.txt"), "linux")
    assert ReleaseInfo.from_dict(release.to_dict()) == release
    with pytest.raises(ValueError):
        ReleaseInfo.from_dict({"version": "1.0.0"})


def test_fetch_latest_sends_no_identifying_data(github) -> None:
    github.publish("1.2.3", {LINUX_ASSET: b"x"})
    with github.client() as client:
        release = fetch_latest(client, "linux")
    assert release is not None
    assert release.version == "1.2.3"
    (request,) = github.requests
    assert request.method == "GET"
    assert request.url.query == b""
    assert request.content == b""
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


def test_fetch_latest_without_any_release_returns_none(github) -> None:
    github.api_status = 404
    with github.client() as client:
        assert fetch_latest(client, "linux") is None


def test_fetch_latest_reports_server_errors(github) -> None:
    github.api_status = 403  # np. przekroczony limit API
    with github.client() as client, pytest.raises(UpdateError):
        fetch_latest(client, "linux")


def test_parse_release_finds_the_signature() -> None:
    release = parse_release(
        payload(LINUX_ASSET, "SHA256SUMS.txt", "SHA256SUMS.txt.minisig"), "linux"
    )
    assert release.signature is not None
    assert release.signature.name == "SHA256SUMS.txt.minisig"
    assert ReleaseInfo.from_dict(release.to_dict()) == release


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("../" + LINUX_ASSET, f"{DOWNLOADS}/a"),
        ("katalog\\" + LINUX_ASSET, f"{DOWNLOADS}/a"),
        (LINUX_ASSET, "http://github.com/a"),
        (LINUX_ASSET, "https://evil.example/a"),
        (LINUX_ASSET, "https://user@github.com/a"),
    ],
)
def test_parse_release_skips_unsafe_assets(name, url) -> None:
    data = {
        "tag_name": "v1.2.3",
        "assets": [{"name": name, "browser_download_url": url, "size": 1}],
    }
    assert parse_release(data, "linux").artifact is None


def test_parse_release_replaces_foreign_page_url() -> None:
    data = {"tag_name": "v1.2.3", "html_url": "javascript:alert(1)", "assets": []}
    assert parse_release(data, "linux").page_url == releases.RELEASES_PAGE_URL


@pytest.mark.parametrize("version", ["../../x", "1.2", "v1.2.3", "01.2.3"])
def test_release_info_rejects_versions_unusable_as_paths(version) -> None:
    with pytest.raises(ValueError):
        ReleaseInfo(version, releases.RELEASES_PAGE_URL, None, None)
