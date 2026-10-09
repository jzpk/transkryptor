"""Pobranie artefaktu nowej wersji z weryfikacją podpisu i sumy SHA256.

Łańcuch zaufania: podpis minisign (``SHA256SUMS.txt.minisig``) potwierdza
``SHA256SUMS.txt`` kluczem wbudowanym w aplikację, a sumy potwierdzają
artefakt. Bez poprawnego podpisu nic nie jest pobierane. Plik jest
zapisywany jako ``.part`` i dopiero po zgodnej sumie zmienia nazwę na
docelową — przerwane albo uszkodzone pobranie nigdy nie zostaje uznane za
gotową aktualizację. Pobrania leżą w pamięci podręcznej użytkownika
(``<cache>/updates/<wersja>/``) razem z podpisanymi sumami, żeby tuż przed
instalacją dało się sprawdzić plik ponownie (``verify_downloaded``);
katalogi innych wersji są usuwane.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

import httpx

from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.paths import user_cache_dir
from transkryptor.update.releases import (
    CHECKSUMS_ASSET,
    SIGNATURE_ASSET,
    ReleaseInfo,
    parse_version,
)
from transkryptor.update.signature import SignatureError, verify_release_checksums

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
    trusted_keys: Iterable[str] | None = None,
) -> Path:
    """Pobiera artefakt wydania dla bieżącej platformy i zwraca jego ścieżkę.

    Gotowy plik z poprzedniego uruchomienia (zgodna suma) jest używany
    ponownie bez pobierania. Błędy połączenia przechodzą jako
    ``httpx.TransportError``; pozostałe problemy jako ``UpdateError``.
    ``should_cancel`` jest sprawdzane między porcjami danych.
    ``trusted_keys=None`` oznacza klucze wbudowane w aplikację.
    """
    artifact, checksums = release.artifact, release.checksums
    if artifact is None or checksums is None:
        raise UpdateError(
            user_message=tr("update.error.no_artifact", version=release.version)
        )
    if release.signature is None:
        raise UpdateError(
            user_message=tr("update.error.signature_missing", version=release.version)
        )
    root = root or default_download_root()
    target_dir = root / release.version
    target = target_dir / artifact.name

    sums = _fetch(client, checksums.url)
    signature = _fetch(client, release.signature.url)
    try:
        verify_release_checksums(
            sums, signature.decode("utf-8", "replace"), release.version, trusted_keys
        )
    except SignatureError as error:
        raise UpdateError(
            user_message=tr("update.error.signature_invalid", version=release.version),
            retry_hint=tr("update.error.signature_invalid.hint"),
        ) from error
    expected = parse_checksums(sums.decode("utf-8", "replace")).get(artifact.name)
    if expected is None:
        raise UpdateError(
            user_message=tr("update.error.no_checksum", name=artifact.name)
        )

    _remove_other_versions(root, keep=release.version)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Podpisane sumy obok artefaktu: instalacja sprawdza plik jeszcze raz.
    _write_file(target_dir / CHECKSUMS_ASSET, sums)
    _write_file(target_dir / SIGNATURE_ASSET, signature)
    if target.is_file() and sha256_of(target) == expected:
        return target

    partial = target.with_name(target.name + PART_SUFFIX)
    digest = hashlib.sha256()
    try:
        with client.stream("GET", artifact.url) as stream:
            if stream.status_code != 200:
                raise UpdateError(
                    user_message=tr(
                        "update.error.download",
                        version=release.version,
                        status=stream.status_code,
                    ),
                    retry_hint=tr("update.error.later.hint"),
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
            user_message=tr("update.error.checksum_mismatch", version=release.version),
            retry_hint=tr("update.error.checksum_mismatch.hint"),
        )
    os.replace(partial, target)
    return target


def verify_downloaded(artifact: Path, trusted_keys: Iterable[str] | None = None) -> str:
    """Ponownie sprawdza pobrany artefakt tuż przed instalacją.

    Podpis sum i suma pliku są liczone od nowa z plików na dysku — plik mógł
    się zmienić od pobrania (godziny wcześniej). Zwraca oczekiwaną sumę
    SHA-256; każdy problem → ``UpdateError``.
    """
    version = artifact.parent.name
    try:
        if parse_version(version) is None:
            raise SignatureError(f"katalog pobrania bez wersji: {version!r}")
        sums = (artifact.parent / CHECKSUMS_ASSET).read_bytes()
        signature = (artifact.parent / SIGNATURE_ASSET).read_text(encoding="utf-8")
        verify_release_checksums(sums, signature, version, trusted_keys)
        expected = parse_checksums(sums.decode("utf-8", "replace")).get(artifact.name)
        if expected is None or sha256_of(artifact) != expected:
            raise SignatureError("suma pliku nie zgadza się z podpisanymi sumami")
    except (OSError, ValueError) as error:
        # Zmieniony albo uszkodzony plik nie zostaje — następny start pobierze
        # wydanie od nowa. Usuwany jest tylko katalog wersji z pobrań.
        if parse_version(version) is not None:
            shutil.rmtree(artifact.parent, ignore_errors=True)
        raise UpdateError(
            user_message=tr("update.error.verify_failed", version=version),
            retry_hint=tr("update.error.verify_failed.hint"),
        ) from error
    return expected


def _fetch(client: httpx.Client, url: str) -> bytes:
    """Mały plik wydania (sumy, podpis); błąd HTTP → ``UpdateError``."""
    response = client.get(url)
    if response.status_code != 200:
        raise UpdateError(
            user_message=tr("update.error.checksums", status=response.status_code),
            retry_hint=tr("update.error.later.hint"),
        )
    return response.content


def _write_file(path: Path, data: bytes) -> None:
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)


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
