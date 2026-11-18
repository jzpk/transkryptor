"""Operacje plikowe wspólne dla aplikacji: zapis atomowy, suma SHA-256
i odczyt danych z limitem rozmiaru (pobrania, elementy archiwów)."""

from __future__ import annotations

import contextlib
import functools
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
    Błąd systemu plików → ``ProjectError`` (zapis projektu, eksportu,
    paczki); bez tej zamiany - :func:`atomic_output_raw`.
    """
    try:
        with atomic_output_raw(target, mode) as handle:
            yield handle
    except OSError as exc:
        raise ProjectError(
            user_message=tr(
                "project.error.save", name=target.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("project.error.save.hint"),
        ) from exc


@contextlib.contextmanager
def atomic_output_raw(
    target: Path, mode: int | None = None, *, durable: bool = True
) -> Iterator[IO[bytes]]:
    """Strumień zapisu atomowego; błąd systemu plików przechodzi jako ``OSError``."""
    with atomic_path(target, mode, durable=durable) as temp, temp.open("wb") as handle:
        yield handle


@contextlib.contextmanager
def atomic_path(
    target: Path,
    mode: int | None = None,
    *,
    suffix: str = ".tmp",
    durable: bool = True,
) -> Iterator[Path]:
    """Ścieżka pliku tymczasowego obok ``target`` dla kodu, który sam otwiera
    plik (np. koder FLAC); po udanym bloku plik zastępuje ``target``.

    Plik tymczasowy dostaje prawa ``mode`` (bez niego - prawa istniejącego
    pliku albo domyślne dla nowego), a przy ``durable`` jest utrwalany
    (``fsync`` pliku i katalogu) - pamięć podręczna, którą da się odtworzyć,
    może z tego zrezygnować. ``suffix`` zachowuje rozszerzenie, po którym
    biblioteki rozpoznają format. Wyjątek w bloku usuwa plik tymczasowy
    i zostawia poprzednią wersję; błąd systemu plików → ``OSError``.
    """
    fd, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=suffix
    )
    os.close(fd)
    temp = Path(name)
    try:
        yield temp
        if durable:
            _fsync_file(temp)
        if os.name == "posix":
            temp.chmod(_target_mode(target) if mode is None else mode)
        temp.replace(target)
        if durable:
            _fsync_directory(target.parent)
    finally:
        temp.unlink(missing_ok=True)


def _fsync_file(path: Path) -> None:
    # Z prawem zapisu: w Windows ``fsync`` (``_commit``) na deskryptorze
    # tylko do odczytu kończy się EBADF.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _target_mode(target: Path) -> int:
    """Prawa istniejącego pliku albo ``0666`` z maską umask dla nowego."""
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        return 0o666 & ~process_umask()


_PROC_STATUS = Path("/proc/self/status")


def process_umask() -> int:
    """Maska umask procesu, odczytana bez jej zmieniania.

    ``os.umask`` odczytuje maskę tylko przez ustawienie nowej, a maska
    dotyczy całego procesu - plik tworzony w tym czasie przez inny wątek
    (pobieranie modelu, kopia nagrania) dostałby prawa ``0666``. W Linuksie
    maskę podaje ``/proc/self/status``; gdzie indziej obowiązuje odczyt
    z :func:`remember_umask` przy starcie programu, przed wątkami.
    """
    try:
        for line in _PROC_STATUS.read_text(encoding="ascii").splitlines():
            if line.startswith("Umask:"):
                return int(line.split()[1], 8)
    except (OSError, ValueError, IndexError):
        pass
    return remember_umask()


@functools.cache
def remember_umask() -> int:
    """Maska umask z pierwszego wywołania (``__main__`` - przed wątkami)."""
    umask = os.umask(0)
    os.umask(umask)
    return umask


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
