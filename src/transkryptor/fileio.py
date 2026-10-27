"""Operacje plikowe wspólne dla aplikacji: zapis atomowy i suma SHA-256."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from transkryptor.errors import ProjectError
from transkryptor.i18n import tr

_HASH_CHUNK = 1 << 20


def write_atomic(target: Path, payload: bytes, mode: int | None = None) -> None:
    """Plik tymczasowy w katalogu docelowym, ``fsync`` i ``os.replace``.

    ``tempfile`` tworzy plik z prawami ``0600``, a ``os.replace`` przenosi je
    na plik docelowy. Dlatego przed podmianą plik dostaje prawa ``mode``,
    a bez niego - prawa istniejącego pliku albo domyślne dla nowego
    (``0666`` z maską umask). Projekt na wspólnym udziale zostaje czytelny
    dla zespołu; autozapis podaje ``0o600``.
    """
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
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
