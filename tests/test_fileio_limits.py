"""Odczyt z limitem rozmiaru: strumienie z sieci i elementy archiwów."""

import io

import pytest

from transkryptor.fileio import SizeLimitError, limited_chunks, read_limited


def test_limited_chunks_passes_data_within_the_limit() -> None:
    assert b"".join(limited_chunks([b"ab", b"cd"], 4)) == b"abcd"


def test_limited_chunks_stops_before_the_chunk_over_the_limit() -> None:
    passed: list[bytes] = []
    with pytest.raises(SizeLimitError) as info:
        for chunk in limited_chunks(iter([b"ab", b"cd", b"e"]), 4):
            passed.append(chunk)
    assert passed == [b"ab", b"cd"]
    assert info.value.limit == 4


def test_read_limited() -> None:
    assert read_limited(io.BytesIO(b"abc"), 3) == b"abc"
    with pytest.raises(SizeLimitError):
        read_limited(io.BytesIO(b"abcd"), 3)
