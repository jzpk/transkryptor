"""Sprawdzanie paczki ``.tkpack`` przy odczycie: nazwy plików, ich
unikalność i zgodność nagrania z projektem. Używa go ``document/pack.py``."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from transkryptor.document.project import loads
from transkryptor.errors import ProjectError
from transkryptor.i18n import tr

# Nazwy urządzeń w Windows - pliku o takim rdzeniu nazwy nie da się zapisać.
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)


def safe_name(name: str) -> str:
    """Sama nazwa pliku, bez katalogów i znaków niedozwolonych w Windows.

    Nazwa urządzenia Windows (``CON``, ``NUL.txt``, ``com1.mp3``...) dostaje
    przedrostek ``_`` - inaczej zapis kończy się niezrozumiałym błędem.
    """
    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = "".join("_" if ch in '<>:"|?*' or ord(ch) < 32 else ch for ch in base)
    cleaned = cleaned.strip(" .")
    if cleaned.split(".", 1)[0].rstrip(" ").upper() in RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def checked_name(value: Any) -> str:
    if not isinstance(value, str) or not value or safe_name(value) != value:
        raise ValueError("nieprawidłowa nazwa pliku w paczce")
    return value


def check_unique_names(names: list[str]) -> None:
    """Pliki paczki trafiają do jednego katalogu - nazwa nie może się powtarzać.

    Porównanie bez wielkości liter (``casefold``), bo w Windows i macOS
    ``Wywiad.mp3`` i ``wywiad.MP3`` to ten sam plik - jeden nadpisałby drugi.
    """
    folded = [name.casefold() for name in names]
    if len(folded) != len(set(folded)):
        raise ValueError("powtórzona nazwa pliku w paczce")


def check_project_audio(project: Path, expected_sha256: str, path: Path) -> None:
    """Suma nagrania w projekcie z paczki musi się zgadzać z manifestem.

    Inaczej projekt wskazywałby inne nagranie niż to, które paczka zawiera
    (albo, bez nagrania, niż to, z którym manifest każe go powiązać).
    """
    if not expected_sha256:
        return
    try:
        audio = loads(project.read_text(encoding="utf-8")).audio
    except ProjectError as exc:
        raise invalid_pack(path) from exc
    if audio is None or audio.sha256.lower() != expected_sha256.lower():
        raise audio_mismatch(path)


def audio_mismatch(path: Path) -> ProjectError:
    return ProjectError(
        user_message=tr("pack.error.audio_mismatch", name=path.name),
        retry_hint=tr("pack.error.invalid.hint"),
    )


def invalid_pack(path: Path) -> ProjectError:
    return ProjectError(
        user_message=tr("pack.error.invalid", name=path.name),
        retry_hint=tr("pack.error.invalid.hint"),
    )


__all__ = [
    "RESERVED_NAMES",
    "audio_mismatch",
    "check_project_audio",
    "check_unique_names",
    "checked_name",
    "invalid_pack",
    "safe_name",
]
