"""Historia zmian pokazywana w aplikacji („Co nowego”), bez zależności od Qt.

Źródłem jest ``CHANGELOG.md`` z repozytorium. Wydanie dołącza go do pakietu
(koło: ``transkryptor/CHANGELOG.md``, PyInstaller: zasób pakietu), a przy
pracy na kodzie źródłowym jest czytany z katalogu repozytorium. Okno pokazuje
sekcje wersji od najnowszej; wstęp dla autorów zmian i pusta sekcja
„Nieopublikowane” są pomijane.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

CHANGELOG_NAME = "CHANGELOG.md"
UNRELEASED = "Nieopublikowane"

# src/transkryptor/changes.py → katalog repozytorium (praca na źródłach).
_SOURCE_CHANGELOG = Path(__file__).resolve().parents[2] / CHANGELOG_NAME
_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")


def changelog_text() -> str | None:
    """Treść ``CHANGELOG.md`` dołączonego do aplikacji albo None, gdy go brak."""
    try:
        return (
            resources.files("transkryptor")
            .joinpath(CHANGELOG_NAME)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError):
        pass
    try:
        return _SOURCE_CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return None


def history_markdown(text: str, unreleased_title: str = UNRELEASED) -> str:
    """Sekcje ``## …`` historii zmian w Markdown, bez wstępu pliku.

    Niepusta sekcja „Nieopublikowane” (wersja rozwojowa) zostaje
    z nagłówkiem ``unreleased_title``; pusta jest pomijana.
    """
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            sections.append((match["title"], []))
        elif sections:
            sections[-1][1].append(line)
    parts: list[str] = []
    for title, body in sections:
        content = "\n".join(body).strip()
        if title == UNRELEASED:
            if not content:
                continue
            title = unreleased_title
        parts.append(f"## {title}\n\n{content}" if content else f"## {title}")
    return "\n\n".join(parts)


__all__ = ["CHANGELOG_NAME", "changelog_text", "history_markdown"]
