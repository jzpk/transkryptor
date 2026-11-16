"""Testy odczytu najnowszego wydania z jego podpisu i porównania wersji."""

from __future__ import annotations

import pytest

from transkryptor.errors import UpdateError
from transkryptor.packaging.metadata import targets
from transkryptor.update import releases
from transkryptor.update.releases import (
    LATEST_SIGNATURE_URL,
    MAX_SMALL_FILE_BYTES,
    ReleaseInfo,
    fetch_latest,
    is_newer,
    parse_version,
)
from transkryptor.update.signature import trusted_comment_for

LINUX_ASSET = "Transkryptor-1.2.3-x86_64.AppImage"
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


def test_fetch_latest_reads_the_signed_version(github) -> None:
    github.publish("1.2.3", {LINUX_ASSET: b"x"})
    with github.client() as client:
        release = fetch_latest(client, "linux")
    assert release is not None
    assert release.version == "1.2.3"
    assert release.signature == github.signature()
    assert release.page_url == (
        "https://github.com/jzpk/transkryptor/releases/tag/v1.2.3"
    )
    assert release.asset_url("SHA256SUMS.txt") == f"{DOWNLOADS}/SHA256SUMS.txt"
    assert release.artifact_suffix == "-x86_64.AppImage"


def test_fetch_latest_does_not_use_the_rate_limited_api(github) -> None:
    """Jedno małe pobranie z github.com: bez api.github.com i bez danych."""
    github.publish("1.2.3", {LINUX_ASSET: b"x"})
    with github.client() as client:
        fetch_latest(client, "linux")
    assert [str(request.url) for request in github.requests] == [
        LATEST_SIGNATURE_URL,
        f"{DOWNLOADS}/SHA256SUMS.txt.minisig",
    ]
    for request in github.requests:
        assert request.method == "GET"
        assert request.url.host == "github.com"
        assert request.url.query == b""
        assert request.content == b""
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
    assert github.downloads == []


def test_fetch_latest_without_any_release_returns_none(github) -> None:
    github.latest_status = 404
    with github.client() as client:
        assert fetch_latest(client, "linux") is None


def test_fetch_latest_reports_server_errors(github) -> None:
    github.latest_status = 503
    with github.client() as client, pytest.raises(UpdateError):
        fetch_latest(client, "linux")


@pytest.mark.parametrize(
    "forgery", ["foreign_key", "garbage", "foreign_comment", "path_version"]
)
def test_fetch_latest_rejects_unverified_versions(github, foreign_key, forgery) -> None:
    github.publish("1.2.3", {LINUX_ASSET: b"x"})
    sums = github.checksums().encode()
    github.signature_override = {
        "foreign_key": lambda: foreign_key.sign(sums, trusted_comment_for("1.2.3")),
        "garbage": lambda: "śmieci",
        "foreign_comment": lambda: github.key.sign(sums, "inny 1.2.3 plik"),
        "path_version": lambda: github.key.sign(sums, trusted_comment_for("../x")),
    }[forgery]()
    with github.client() as client, pytest.raises(UpdateError):
        fetch_latest(client, "linux")


def test_endless_signature_is_not_read_into_memory(github) -> None:
    sent: list[int] = []

    def endless():
        while True:
            sent.append(4096)
            yield b"x" * 4096

    github.streams["SHA256SUMS.txt.minisig"] = endless
    with github.client() as client, pytest.raises(UpdateError):
        fetch_latest(client, "linux")
    assert sum(sent) <= MAX_SMALL_FILE_BYTES + 4096


@pytest.mark.parametrize("version", ["../../x", "1.2", "v1.2.3", "01.2.3"])
def test_release_info_rejects_versions_unusable_as_paths(version) -> None:
    with pytest.raises(ValueError):
        ReleaseInfo(version, "podpis")


@pytest.mark.parametrize("name", ["../plik", "a/b", "a\\b", ".."])
def test_release_asset_url_rejects_paths(name) -> None:
    with pytest.raises(ValueError):
        ReleaseInfo("1.2.3", "podpis").asset_url(name)


@pytest.mark.parametrize(
    "location",
    ["https://evil.example/plik", "http://github.com/jzpk/transkryptor/x"],
)
def test_update_client_refuses_redirect_outside_github(github, location) -> None:
    import httpx

    from transkryptor.update.service import default_client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in releases.UPDATE_HOSTS:
            return httpx.Response(302, headers={"Location": location})
        raise AssertionError(f"żądanie do {request.url}")

    hooks = default_client().event_hooks
    with (
        httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
            event_hooks=hooks,
        ) as client,
        pytest.raises(UpdateError) as info,
    ):
        releases.fetch_latest(client, "linux")
    assert "niedozwolony adres" in info.value.user_message


def test_update_client_follows_redirect_to_release_assets() -> None:
    import httpx

    target = "https://release-assets.githubusercontent.com/plik"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == target:
            return httpx.Response(200, content=b"ok")
        return httpx.Response(302, headers={"Location": target})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        event_hooks={"request": [releases.check_request_host]},
    ) as client:
        response = client.get("https://github.com/jzpk/transkryptor/releases/x")
    assert response.content == b"ok"
