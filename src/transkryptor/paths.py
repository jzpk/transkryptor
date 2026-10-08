"""Katalogi danych i pamięci podręcznej użytkownika (per OS, bez Qt).

Windows: ``%APPDATA%\\Transkryptor`` (dane) i ``%LOCALAPPDATA%\\Transkryptor``
(pamięć podręczna). Linux: katalogi XDG z nazwą ``transkryptor``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "transkryptor"
WINDOWS_APP_DIR_NAME = "Transkryptor"


def user_data_dir() -> Path:
    """Trwałe dane aplikacji: modele ASR, stan sprawdzania aktualizacji."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / WINDOWS_APP_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / WINDOWS_APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def user_cache_dir() -> Path:
    """Dane odtwarzalne, które można usunąć bez straty: pobrane aktualizacje."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / WINDOWS_APP_DIR_NAME / "cache"
        return Path.home() / "AppData" / "Local" / WINDOWS_APP_DIR_NAME / "cache"
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".cache" / APP_DIR_NAME
