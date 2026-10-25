"""Czcionka tekstu transkrypcji dołączona do aplikacji (Charis SIL, OFL 1.1).

Czcionka jest rejestrowana w Qt przy tworzeniu okna (bez instalacji
w systemie) i jest domyślna dla edytora oraz eksportu ODT/PDF; DOCX zapisuje
jej nazwę - na komputerze bez Charis SIL Word podstawi inną czcionkę.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from PySide6.QtGui import QFontDatabase

DEFAULT_TEXT_FONT = "Charis SIL"
FONT_FILES = (
    "CharisSIL-Regular.ttf",
    "CharisSIL-Bold.ttf",
    "CharisSIL-Italic.ttf",
    "CharisSIL-BoldItalic.ttf",
)


@cache
def register_fonts() -> bool:
    """Rejestruje dołączone pliki czcionki; True, gdy rodzina jest dostępna."""
    package = resources.files("transkryptor").joinpath("fonts")
    for name in FONT_FILES:
        try:
            data = package.joinpath(name).read_bytes()
        except OSError:
            continue
        QFontDatabase.addApplicationFontFromData(data)
    return DEFAULT_TEXT_FONT in QFontDatabase.families()


def text_font_family(configured: str) -> str:
    """Czcionka tekstu: wybrana w ustawieniach albo dołączona (gdy dostępna)."""
    if configured:
        return configured
    return DEFAULT_TEXT_FONT if register_fonts() else ""
