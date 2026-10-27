"""Odwołanie do nagrania: suma SHA-256 i ścieżki względem pliku projektu."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from transkryptor.document.project.model import AudioRef
from transkryptor.fileio import file_sha256


def audio_ref(path: str | Path) -> AudioRef:
    """Odwołanie do nagrania z sumą SHA-256 (plik musi istnieć)."""
    absolute = Path(path).resolve()
    return AudioRef(absolute_path=str(absolute), sha256=file_sha256(absolute))


def relative_audio_path(audio_path: str | Path, project_path: Path) -> str | None:
    """Ścieżka nagrania względem katalogu projektu (zapis POSIX).

    None, gdy ścieżki względnej nie da się zbudować (inny dysk w Windows).
    """
    try:
        relative = os.path.relpath(
            Path(audio_path).resolve(), Path(project_path).resolve().parent
        )
    except ValueError:
        return None
    return Path(relative).as_posix()


def resolve_audio(audio: AudioRef, project_path: Path | None) -> Path | None:
    """Istniejący plik nagrania: najpierw ścieżka względna, potem bezwzględna."""
    candidates: list[Path] = []
    if audio.relative_path and project_path is not None:
        candidates.append(
            Path(project_path).parent.joinpath(
                *PurePosixPath(audio.relative_path).parts
            )
        )
    candidates.append(Path(audio.absolute_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
