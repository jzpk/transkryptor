"""Długość nagrania z nagłówka pliku, bez dekodowania dźwięku (bez Qt)."""

from __future__ import annotations

from pathlib import Path


def duration_ms(path: Path) -> int | None:
    """Długość nagrania w ms (None - nie udało się jej odczytać)."""
    import av

    try:
        with av.open(str(path)) as container:
            if container.duration:
                return int(container.duration * 1000 // av.time_base)
            stream = container.streams.audio[0]
            if stream.duration and stream.time_base:
                return int(stream.duration * stream.time_base * 1000)
    except (OSError, IndexError, av.FFmpegError):
        return None
    return None
