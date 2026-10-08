"""Zapis wielokropka: styl ``…`` (U+2026) albo ``...`` (trzy kropki).

Pauza i urwane słowo mogą być zapisane oboma znakami; konwencję zespołu
wyznacza ustawienie użytkownika (domyślnie ``…`` — decyzja w
``specs/transcription-rules.md``). Moduł nie zależy od Qt: wyszukuje
wielokropki, wskazuje te w zapisie innym niż wybrany i normalizuje tekst.

Dopisek ``[...]`` i marker pominięcia ``[…?]`` mają stałą postać, więc ich
wnętrze nie jest traktowane jako wielokropek. Tak samo ``…`` tuż po ``[`` —
to (być może wadliwy) marker pominięcia, który zgłasza VAL-03.
"""

from __future__ import annotations

import re
from enum import StrEnum


class EllipsisStyle(StrEnum):
    """Styl zapisu wielokropka."""

    UNICODE = "unicode"  # …
    ASCII = "ascii"  # ...


DEFAULT_ELLIPSIS_STYLE = EllipsisStyle.UNICODE

_TEXT = {EllipsisStyle.UNICODE: "…", EllipsisStyle.ASCII: "..."}

# Stałe markery najpierw: ich wnętrze nie jest wielokropkiem.
_ELLIPSIS_RE = re.compile(r"\[…\?\]|\[\.\.\.\]|\[…|\.\.\.|…")
_FIXED_MARKERS = ("[…?]", "[...]", "[…")


def ellipsis_text(style: EllipsisStyle) -> str:
    """Znak (lub znaki) wielokropka w danym stylu."""
    return _TEXT[EllipsisStyle(style)]


def pause_text(style: EllipsisStyle) -> str:
    """Marker pauzy z odstępem po obu stronach, np. ``" … "``."""
    return f" {ellipsis_text(style)} "


def find_ellipses(text: str) -> list[tuple[int, int]]:
    """Zakresy wszystkich wielokropków (``...`` i ``…``) poza stałymi markerami."""
    return [
        match.span()
        for match in _ELLIPSIS_RE.finditer(text)
        if match.group() not in _FIXED_MARKERS
    ]


def foreign_ellipses(text: str, style: EllipsisStyle) -> list[tuple[int, int]]:
    """Zakresy wielokropków zapisanych inaczej niż ``style``."""
    wanted = ellipsis_text(style)
    return [
        (start, end) for start, end in find_ellipses(text) if text[start:end] != wanted
    ]


def normalize_ellipses(text: str, style: EllipsisStyle) -> str:
    """Tekst z wszystkimi wielokropkami w stylu ``style``."""
    wanted = ellipsis_text(style)
    parts: list[str] = []
    last = 0
    for start, end in foreign_ellipses(text, style):
        parts.append(text[last:start])
        parts.append(wanted)
        last = end
    parts.append(text[last:])
    return "".join(parts)
