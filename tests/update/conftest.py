"""Wspólne imitacje GitHub Releases: odpowiedź API i serwer plików."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx
import pytest

from transkryptor.update.releases import LATEST_RELEASE_URL

DOWNLOAD_BASE = "https://github.com/jzpk/transkryptor/releases/download"


class FakeGitHub:
    """Serwer imitujący API wydań i pliki wydania; liczy zapytania."""

    def __init__(self) -> None:
        self.version = "9.9.9"
        self.api_status = 200
        self.files: dict[str, bytes] = {}
        self.checksums_override: str | None = None
        self.offline = False
        self.api_calls = 0
        self.downloads: list[str] = []
        self.requests: list[httpx.Request] = []

    def publish(self, version: str, files: dict[str, bytes]) -> None:
        self.version = version
        self.files = files

    def asset_url(self, name: str) -> str:
        return f"{DOWNLOAD_BASE}/v{self.version}/{name}"

    def payload(self) -> dict:
        names = [*self.files, "SHA256SUMS.txt"]
        return {
            "tag_name": f"v{self.version}",
            "html_url": f"https://github.com/jzpk/transkryptor/releases/tag/v{self.version}",
            "assets": [
                {"name": name, "browser_download_url": self.asset_url(name), "size": 1}
                for name in names
            ],
        }

    def checksums(self) -> str:
        if self.checksums_override is not None:
            return self.checksums_override
        return "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in self.files.items()
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("brak sieci", request=request)
        url = str(request.url)
        if url == LATEST_RELEASE_URL:
            self.api_calls += 1
            if self.api_status != 200:
                return httpx.Response(self.api_status, json={"message": "x"})
            return httpx.Response(200, json=self.payload())
        name = url.rsplit("/", 1)[-1]
        if name == "SHA256SUMS.txt":
            return httpx.Response(200, text=self.checksums())
        if name in self.files:
            self.downloads.append(name)
            return httpx.Response(200, content=self.files[name])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def client_factory(github: FakeGitHub) -> Callable[[], httpx.Client]:
    return github.client
