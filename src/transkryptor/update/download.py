"""Pobranie artefaktu nowej wersji z weryfikacją sumy SHA256.

Suma pochodzi z ``SHA256SUMS.txt`` opublikowanego razem z wydaniem. Plik jest
zapisywany jako ``.part`` i dopiero po zgodnej sumie zmienia nazwę na
docelową — przerwane albo uszkodzone pobranie nigdy nie zostaje uznane za
gotową aktualizację. Pobrania leżą w pamięci podręcznej użytkownika
(``<cache>/updates/<wersja>/``); katalogi innych wersji są usuwane.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx

from transkryptor.errors import UpdateError
from transkryptor.paths import user_cache_dir
from transkryptor.update.releases import ReleaseInfo

CHUNK_SIZE = 1 << 20
PART_SUFFIX = ".part"


class DownloadCancelled(Exception):
    """Pobieranie przerwane, bo aplikacja się zamyka (nie jest błędem)."""


def default_download_root() -> Path:
    return user_cache_dir() / "updates"


def parse_checksums(text: str) -> dict[str, str]:
    """Format ``sha256sum``: ``<hex>  <nazwa>`` (także ``*<nazwa>``)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            digest, name = parts
            sums[name.lstrip("*").strip()] = digest.lower()
    return sums


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_release(
    release: ReleaseInfo,
    client: httpx.Client,
    root: Path | None = None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> Path:
    """Pobiera artefakt wydania dla bieżącej platformy i zwraca jego ścieżkę.

    Gotowy plik z poprzedniego uruchomienia (zgodna suma) jest używany
    ponownie bez pobierania. Błędy połączenia przechodzą jako
    ``httpx.TransportError``; pozostałe problemy jako ``UpdateError``.
    ``should_cancel`` jest sprawdzane między porcjami danych.
    """
    artifact, checksums = release.artifact, release.checksums
    if artifact is None or checksums is None:
        raise UpdateError(
            user_message=(
                f"Wydanie {release.version} nie zawiera pliku dla tego systemu."
            )
        )
    root = root or default_download_root()
    target_dir = root / release.version
    target = target_dir / artifact.name

    response = client.get(checksums.url)
    if response.status_code != 200:
        raise UpdateError(
            user_message=(
                "Nie udało się pobrać sum kontrolnych wydania "
                f"(HTTP {response.status_code})."
            ),
            retry_hint="Spróbuj ponownie później.",
        )
    expected = parse_checksums(response.text).get(artifact.name)
    if expected is None:
        raise UpdateError(
            user_message=f"Brak sumy kontrolnej pliku {artifact.name} w wydaniu."
        )

    _remove_other_versions(root, keep=release.version)
    if target.is_file() and sha256_of(target) == expected:
        return target

    target_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + PART_SUFFIX)
    digest = hashlib.sha256()
    try:
        with client.stream("GET", artifact.url) as stream:
            if stream.status_code != 200:
                raise UpdateError(
                    user_message=(
                        f"Nie udało się pobrać wersji {release.version} "
                        f"(HTTP {stream.status_code})."
                    ),
                    retry_hint="Spróbuj ponownie później.",
                )
            with partial.open("wb") as handle:
                for chunk in stream.iter_bytes(chunk_size=CHUNK_SIZE):
                    if should_cancel():
                        raise DownloadCancelled()
                    handle.write(chunk)
                    digest.update(chunk)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != expected:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            user_message=(
                f"Pobrany plik wersji {release.version} ma niezgodną sumę "
                "kontrolną i został odrzucony."
            ),
            retry_hint="Aktualizacja zostanie pobrana ponownie przy kolejnym starcie.",
        )
    os.replace(partial, target)
    return target


def clear_downloads(root: Path | None = None) -> None:
    """Usuwa wszystkie pobrania (aplikacja jest już w najnowszej wersji)."""
    _remove_other_versions(root or default_download_root(), keep=None)


def _remove_other_versions(root: Path, keep: str | None) -> None:
    """Usuwa pobrania innych wersji (zainstalowane albo nieaktualne)."""
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.name != keep and entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
