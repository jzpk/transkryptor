"""Wspólne pobieranie plików (transkryptor.net)."""

from __future__ import annotations

import gzip
import hashlib

import httpx
import pytest

from transkryptor.fileio import SizeLimitError
from transkryptor.net import (
    DownloadCancelled,
    content_length,
    host_matches,
    stream_to_file,
)

DATA = b"dane pliku " * 1000


def respond(content: bytes, headers: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_content_length_ignores_encoded_bodies() -> None:
    plain = httpx.Response(200, headers={"content-length": "12"})
    assert content_length(plain) == 12
    encoded = httpx.Response(
        200, headers={"content-length": "12", "content-encoding": "gzip"}
    )
    assert content_length(encoded) is None
    assert content_length(httpx.Response(200, headers={"content-length": "x"})) is None
    assert content_length(httpx.Response(200, headers={"content-length": "-1"})) is None


def test_stream_counts_decoded_bytes(tmp_path) -> None:
    packed = gzip.compress(DATA)
    headers = {"content-encoding": "gzip", "content-length": str(len(packed))}
    chunks: list[int] = []
    with (
        respond(packed, headers) as client,
        client.stream("GET", "https://x/") as response,
    ):
        assert content_length(response) is None
        size, digest = stream_to_file(
            response,
            tmp_path / "plik.part",
            limit=len(DATA),
            should_cancel=lambda: False,
            on_chunk=chunks.append,
        )
    assert size == sum(chunks) == len(DATA)
    assert digest == hashlib.sha256(DATA).hexdigest()
    assert (tmp_path / "plik.part").read_bytes() == DATA


def test_stream_stops_at_the_limit_and_on_cancel(tmp_path) -> None:
    with respond(DATA, {}) as client:
        with (
            client.stream("GET", "https://x/") as response,
            pytest.raises(SizeLimitError),
        ):
            stream_to_file(
                response,
                tmp_path / "a.part",
                limit=len(DATA) - 1,
                should_cancel=lambda: False,
            )
        with (
            client.stream("GET", "https://x/") as response,
            pytest.raises(DownloadCancelled),
        ):
            stream_to_file(
                response,
                tmp_path / "b.part",
                limit=len(DATA),
                should_cancel=lambda: True,
            )


def test_host_patterns_cover_subdomains_only() -> None:
    allowed = ("huggingface.co", "*.hf.co")
    assert host_matches("huggingface.co", allowed)
    assert host_matches("cdn-lfs.hf.co", allowed)
    assert host_matches("CAS-BRIDGE.XETHUB.HF.CO", allowed)
    assert not host_matches("hf.co.evil.example", allowed)
    assert not host_matches("evilhf.co", allowed)
    assert not host_matches("www.huggingface.co", allowed)
