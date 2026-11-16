"""Wspólne imitacje GitHub Releases: serwer plików wydania (z przekierowaniem
``latest/download``) i klucz podpisujący wydania (format minisign)."""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Callable, Iterator

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from transkryptor.update import keys
from transkryptor.update.releases import LATEST_SIGNATURE_URL
from transkryptor.update.signature import trusted_comment_for

DOWNLOAD_BASE = "https://github.com/jzpk/transkryptor/releases/download"


class ReleaseKey:
    """Klucz Ed25519 podpisujący jak ``minisign -S`` (algorytm ED, prehash)."""

    def __init__(self) -> None:
        self._private = Ed25519PrivateKey.generate()
        self.key_id = os.urandom(8)

    @property
    def public(self) -> str:
        """Druga linia pliku ``.pub`` z ``minisign -G``."""
        raw = self._private.public_key().public_bytes_raw()
        return base64.b64encode(b"Ed" + self.key_id + raw).decode()

    def sign(self, data: bytes, comment: str, *, algorithm: bytes = b"ED") -> str:
        """Treść pliku ``.minisig`` dla ``data`` z zaufanym komentarzem."""
        message = hashlib.blake2b(data, digest_size=64).digest()
        if algorithm == b"Ed":
            message = data
        signature = self._private.sign(message)
        global_signature = self._private.sign(signature + comment.encode())
        return (
            "untrusted comment: signature from minisign secret key\n"
            f"{base64.b64encode(algorithm + self.key_id + signature).decode()}\n"
            f"trusted comment: {comment}\n"
            f"{base64.b64encode(global_signature).decode()}\n"
        )


class FakeGitHub:
    """Serwer imitujący pliki wydań GitHub; liczy sprawdzenia wersji."""

    def __init__(self, key: ReleaseKey) -> None:
        self.key = key
        self.version = "9.9.9"
        # Kod odpowiedzi na ``latest/download`` (404: brak wydań).
        self.latest_status = 302
        self.files: dict[str, bytes] = {}
        self.checksums_override: str | None = None
        self.signature_override: str | None = None
        # Treść podstawiana zamiast pliku (np. strumień bez końca).
        self.streams: dict[str, Callable[[], Iterator[bytes]]] = {}
        self.offline = False
        self.latest_calls = 0
        self.downloads: list[str] = []
        self.requests: list[httpx.Request] = []

    def publish(self, version: str, files: dict[str, bytes]) -> None:
        self.version = version
        self.files = files

    def asset_url(self, name: str) -> str:
        return f"{DOWNLOAD_BASE}/v{self.version}/{name}"

    def checksums(self) -> str:
        if self.checksums_override is not None:
            return self.checksums_override
        return "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in self.files.items()
        )

    def signature(self) -> str:
        if self.signature_override is not None:
            return self.signature_override
        return self.key.sign(
            self.checksums().encode(), trusted_comment_for(self.version)
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("brak sieci", request=request)
        url = str(request.url)
        if url == LATEST_SIGNATURE_URL:
            self.latest_calls += 1
            if self.latest_status != 302:
                return httpx.Response(self.latest_status, text="Not Found")
            location = self.asset_url("SHA256SUMS.txt.minisig")
            return httpx.Response(302, headers={"Location": location})
        prefix, _, name = url.rpartition("/")
        if prefix != f"{DOWNLOAD_BASE}/v{self.version}":
            return httpx.Response(404)
        if name in self.streams:
            return httpx.Response(200, content=self.streams[name]())
        if name == "SHA256SUMS.txt":
            return httpx.Response(200, text=self.checksums())
        if name == "SHA256SUMS.txt.minisig":
            return httpx.Response(200, text=self.signature())
        if name in self.files:
            self.downloads.append(name)
            return httpx.Response(200, content=self.files[name])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handler), follow_redirects=True
        )


@pytest.fixture(scope="session")
def release_key() -> ReleaseKey:
    return ReleaseKey()


@pytest.fixture(scope="session")
def foreign_key() -> ReleaseKey:
    """Klucz, któremu aplikacja nie ufa (np. napastnika)."""
    return ReleaseKey()


@pytest.fixture(autouse=True)
def trusted_release_key(monkeypatch, release_key: ReleaseKey) -> None:
    """Aplikacja w testach ufa kluczowi testowemu zamiast wbudowanemu."""
    monkeypatch.setattr(keys, "TRUSTED_KEYS", (release_key.public,))


@pytest.fixture
def github(release_key: ReleaseKey) -> FakeGitHub:
    return FakeGitHub(release_key)


@pytest.fixture
def client_factory(github: FakeGitHub) -> Callable[[], httpx.Client]:
    return github.client
