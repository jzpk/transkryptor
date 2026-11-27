"""Obsługiwane formaty nagrań (bez Qt - korzysta z nich też ``corpus``).

Formaty dekodowane zarówno przez Qt Multimedia (odtwarzanie), jak i przez
PyAV/FFmpeg (ASR). Oba backendy korzystają z FFmpeg.
"""

from __future__ import annotations

from pathlib import Path

from transkryptor.i18n import tr

SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
)
SUPPORTED_FORMATS_LABEL = ", ".join(
    suffix.removeprefix(".").upper() for suffix in SUPPORTED_SUFFIXES
)


def is_audio(path: str | Path) -> bool:
    """Plik ma rozszerzenie obsługiwanego nagrania (bez względu na wielkość liter)."""
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def file_dialog_filter() -> str:
    """Filtr okna wyboru pliku dla obsługiwanych nagrań."""
    patterns = " ".join(f"*{suffix}" for suffix in SUPPORTED_SUFFIXES)
    return tr("player.file_filter", patterns=patterns)
