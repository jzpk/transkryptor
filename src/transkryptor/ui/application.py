"""Obiekt aplikacji Qt z liczbami w formacie niezależnym od języka systemu.

Na Linuksie ``QApplication`` wywołuje ``setlocale(LC_ALL, "")``, więc
przy polskim języku systemu przecinek staje się separatorem dziesiętnym
także dla bibliotek C. FFmpeg (PyAV) czyta wtedy argumenty filtrów takie
jak ``e=12.5`` jako błędne (``EINVAL``) i filtry odsłuchu nie działają.
Qt formatuje liczby przez ``QLocale``, więc przywrócenie ``LC_NUMERIC``
do ``C`` nie zmienia niczego w interfejsie.
"""

from __future__ import annotations

import locale
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication


class Application(QApplication):
    """``QApplication`` z ``LC_NUMERIC=C`` dla bibliotek C (FFmpeg, ASR)."""

    def __init__(self, argv: Sequence[str]) -> None:
        super().__init__(list(argv))
        locale.setlocale(locale.LC_NUMERIC, "C")
