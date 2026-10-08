"""Sumy kontrolne artefaktów wydania.

Lista kontrolna z ``specs/delivery.md`` wymaga opublikowania sum kontrolnych
razem z artefaktami. Format pliku jest zgodny z ``sha256sum`` (GNU
coreutils), więc odbiorca sprawdza wydanie jednym poleceniem:

    sha256sum --check SHA256SUMS.txt
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

CHECKSUM_FILE = "SHA256SUMS.txt"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Checksum:
    """Suma kontrolna pojedynczego artefaktu."""

    name: str
    digest: str
    size_bytes: int


def sha256_file(path: Path) -> str:
    """Suma SHA-256 pliku, liczona strumieniowo (artefakty mają setki MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def checksums_for(paths: Iterable[Path]) -> tuple[Checksum, ...]:
    """Sumy kontrolne podanych plików, posortowane po nazwie."""
    results = [
        Checksum(
            name=path.name, digest=sha256_file(path), size_bytes=path.stat().st_size
        )
        for path in paths
    ]
    return tuple(sorted(results, key=lambda item: item.name))


def render_checksums(entries: Iterable[Checksum]) -> str:
    """Treść pliku w formacie ``sha256sum`` (dwie spacje: tryb tekstowy)."""
    return "".join(f"{entry.digest}  {entry.name}\n" for entry in entries)


def write_checksums(paths: Iterable[Path], dest_dir: Path) -> Path:
    """Zapisuje ``SHA256SUMS.txt`` obok artefaktów i zwraca ścieżkę pliku."""
    entries = checksums_for(paths)
    target = dest_dir / CHECKSUM_FILE
    target.write_text(render_checksums(entries), encoding="utf-8")
    return target


def verify_checksums(checksum_file: Path, base_dir: Path | None = None) -> list[str]:
    """Sprawdza plik sum kontrolnych; zwraca listę problemów (pusta = zgoda)."""
    root = base_dir or checksum_file.parent
    problems: list[str] = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        path = root / name.strip()
        if not path.is_file():
            problems.append(f"brak pliku: {name.strip()}")
            continue
        if sha256_file(path) != digest.strip():
            problems.append(f"niezgodna suma kontrolna: {name.strip()}")
    return problems


__all__ = [
    "CHECKSUM_FILE",
    "Checksum",
    "checksums_for",
    "render_checksums",
    "sha256_file",
    "verify_checksums",
    "write_checksums",
]
