"""Operacje plikowe wspólne dla aplikacji: zapis atomowy, suma SHA-256
i odczyt danych z limitem rozmiaru (pobrania, elementy archiwów)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import tempfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import IO

from transkryptor.errors import ProjectError
from transkryptor.i18n import tr

_HASH_CHUNK = 1 << 20


class SizeLimitError(ValueError):
    """Dane są dłuższe niż dozwolony limit (np. strumień z serwera)."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"dane przekraczają limit {limit} B")
        self.limit = limit


def limited_chunks(chunks: Iterable[bytes], limit: int) -> Iterator[bytes]:
    """Przepuszcza porcje, dopóki ich łączna długość nie przekroczy ``limit``.

    Porcja, która przekroczyłaby limit, nie jest oddawana - zamiast niej
    :class:`SizeLimitError`. Chroni dysk i pamięć przed strumieniem bez
    końca, zanim suma kontrolna odrzuci dane.
    """
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > limit:
            raise SizeLimitError(limit)
        yield chunk


def read_limited(stream: IO[bytes], limit: int) -> bytes:
    """Cały strumień, gdy ma najwyżej ``limit`` bajtów; dłuższy → ``SizeLimitError``."""
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise SizeLimitError(limit)
    return data


def write_atomic(target: Path, payload: bytes, mode: int | None = None) -> None:
    """Plik tymczasowy w katalogu docelowym, ``fsync`` i ``os.replace``.

    ``tempfile`` tworzy plik z prawami ``0600``, a ``os.replace`` przenosi je
    na plik docelowy. Dlatego przed podmianą plik dostaje prawa ``mode``,
    a bez niego - prawa istniejącego pliku albo domyślne dla nowego
    (``0666`` z maską umask). Projekt na wspólnym udziale zostaje czytelny
    dla zespołu; autozapis podaje ``0o600``.
    """
    with atomic_output(target, mode) as handle:
        handle.write(payload)


@contextlib.contextmanager
def atomic_output(target: Path, mode: int | None = None) -> Iterator[IO[bytes]]:
    """Strumień zapisu atomowego - jak :func:`write_atomic` dla dużych plików.

    Plik docelowy powstaje dopiero po udanym zakończeniu bloku ``with``;
    wyjątek w bloku zostawia poprzednią wersję i usuwa plik tymczasowy.
    Błąd systemu plików → ``ProjectError``.
    """
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            Path(temp_name).chmod(_target_mode(target) if mode is None else mode)
        Path(temp_name).replace(target)
        temp_name = None
        _fsync_directory(target.parent)
    except OSError as exc:
        raise ProjectError(
            user_message=tr(
                "project.error.save", name=target.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("project.error.save.hint"),
        ) from exc
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def _target_mode(target: Path) -> int:
    """Prawa istniejącego pliku albo ``0666`` z maską umask dla nowego."""
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _fsync_directory(directory: Path) -> None:
    """Utrwala wpis katalogu po ``os.replace`` (ext4/XFS); tylko POSIX."""
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # część systemów plików (np. udziały sieciowe) tego nie wspiera
    finally:
        os.close(fd)


def file_sha256(
    path: str | Path, should_cancel: Callable[[], bool] | None = None
) -> str:
    """Suma SHA-256 pliku; ``should_cancel`` przerywa liczenie (InterruptedError)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            if should_cancel is not None and should_cancel():
                raise InterruptedError(str(path))
            digest.update(chunk)
    return digest.hexdigest()
