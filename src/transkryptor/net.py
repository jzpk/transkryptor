"""Wspólne pobieranie plików przez HTTP (aktualizacje i modele ASR), bez Qt.

Strumień jest zapisywany porcjami do pliku tymczasowego (``.part``), z sumą
SHA-256 liczoną w locie, limitem długości (``SizeLimitError`` przerywa
pobieranie od razu - serwer pośredni nie zapełni dysku) i kooperacyjnym
anulowaniem między porcjami (:class:`DownloadCancelled`). Weryfikację sumy
i przeniesienie pod docelową nazwę robi wywołujący.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from transkryptor.fileio import limited_chunks

if TYPE_CHECKING:
    import httpx

CHUNK_SIZE = 1 << 20


class DownloadCancelled(Exception):
    """Pobieranie przerwane na życzenie (zamknięcie programu, „Anuluj”)."""


def content_length(response: httpx.Response) -> int | None:
    """Długość treści z nagłówka; None, gdy jej nie ma albo treść jest kodowana.

    Przy ``Content-Encoding`` (np. gzip) nagłówek podaje długość po
    kompresji, a ``iter_bytes`` zwraca dane po dekompresji - takiej długości
    nie da się użyć ani jako limitu, ani do porównania z rozmiarem pliku.
    """
    if response.headers.get("content-encoding", "identity") != "identity":
        return None
    try:
        length = int(response.headers["content-length"])
    except (KeyError, ValueError):
        return None
    return length if length >= 0 else None


def stream_to_file(
    response: httpx.Response,
    partial: Path,
    *,
    limit: int,
    should_cancel: Callable[[], bool],
    on_chunk: Callable[[int], None] | None = None,
) -> tuple[int, str]:
    """Zapisuje treść odpowiedzi do ``partial``; zwraca (rozmiar, SHA-256).

    Dłuższy niż ``limit`` strumień → ``SizeLimitError``, ``should_cancel``
    → :class:`DownloadCancelled`; ``on_chunk`` dostaje długość każdej porcji.
    """
    digest = hashlib.sha256()
    size = 0
    with partial.open("wb") as handle:
        chunks = response.iter_bytes(chunk_size=CHUNK_SIZE)
        for chunk in limited_chunks(chunks, limit):
            if should_cancel():
                raise DownloadCancelled()
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if on_chunk is not None:
                on_chunk(len(chunk))
    return size, digest.hexdigest()


__all__ = ["CHUNK_SIZE", "DownloadCancelled", "content_length", "stream_to_file"]
