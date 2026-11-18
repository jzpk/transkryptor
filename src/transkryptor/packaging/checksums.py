"""Sumy kontrolne artefaktów wydania.

Lista kontrolna wydania wymaga opublikowania sum kontrolnych
razem z artefaktami. Format pliku jest zgodny z ``sha256sum`` (GNU
coreutils), więc odbiorca sprawdza wydanie jednym poleceniem:

    sha256sum --check SHA256SUMS.txt
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from transkryptor.fileio import file_sha256

CHECKSUM_FILE = "SHA256SUMS.txt"


@dataclass(frozen=True)
class Checksum:
    """Suma kontrolna pojedynczego artefaktu."""

    name: str
    digest: str
    size_bytes: int


def checksums_for(paths: Iterable[Path]) -> tuple[Checksum, ...]:
    """Sumy kontrolne podanych plików, posortowane po nazwie."""
    results = [
        Checksum(
            name=path.name, digest=file_sha256(path), size_bytes=path.stat().st_size
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
        if file_sha256(path) != digest.strip():
            problems.append(f"niezgodna suma kontrolna: {name.strip()}")
    return problems


__all__ = [
    "CHECKSUM_FILE",
    "Checksum",
    "checksums_for",
    "render_checksums",
    "verify_checksums",
    "write_checksums",
]
