"""Historia zmian pokazywana w aplikacji („Co nowego”), bez zależności od Qt.

Źródłem jest ``CHANGELOG.md`` z repozytorium. Wydanie dołącza go do pakietu
(koło: ``transkryptor/CHANGELOG.md``, PyInstaller: zasób pakietu), a przy
pracy na kodzie źródłowym jest czytany z katalogu repozytorium razem
z fragmentami niewydanych zmian (``changelog.d/*.md``), które okno pokazuje
jako sekcję „Nieopublikowane”. Okno pokazuje sekcje wersji od najnowszej;
wstęp dla autorów zmian i pusta sekcja „Nieopublikowane” są pomijane.

Fragment to plik Markdown z jedną albo kilkoma pozycjami listy, dodawany
razem z kodem zmiany. Wydanie składa fragmenty w sekcję wersji
(``packaging.changelog``) - dzięki osobnym plikom gałęzie wydań i prace
równoległe nie kłócą się o jedną sekcję pliku.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

CHANGELOG_NAME = "CHANGELOG.md"
FRAGMENTS_DIR_NAME = "changelog.d"
FRAGMENTS_README = "README.md"
UNRELEASED = "Nieopublikowane"

# src/transkryptor/changes.py → katalog repozytorium (praca na źródłach).
_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_CHANGELOG = _SOURCE_ROOT / CHANGELOG_NAME
_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")


def fragment_files(directory: Path) -> list[Path]:
    """Fragmenty niewydanych zmian w kolejności nazw (bez ``README.md``)."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob("*.md")
        if path.is_file() and path.name != FRAGMENTS_README
    )


def unreleased_text(directory: Path) -> str:
    """Treść fragmentów sklejona w jedną listę; pusty napis, gdy ich brak."""
    parts = [
        path.read_text(encoding="utf-8").strip() for path in fragment_files(directory)
    ]
    return "\n\n".join(part for part in parts if part)


def with_unreleased(text: str, unreleased: str) -> str:
    """Historia zmian z sekcją „Nieopublikowane” przed pierwszą wersją."""
    if not unreleased:
        return text
    lines = text.splitlines()
    index = next(
        (i for i, line in enumerate(lines) if _HEADING.match(line)), len(lines)
    )
    lines[index:index] = [f"## {UNRELEASED}", "", unreleased, ""]
    return "\n".join(lines) + "\n"


def changelog_text() -> str | None:
    """Treść ``CHANGELOG.md`` dołączonego do aplikacji albo None, gdy go brak.

    Przy pracy na źródłach dochodzą do niej fragmenty niewydanych zmian.
    """
    try:
        return (
            resources.files("transkryptor")
            .joinpath(CHANGELOG_NAME)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError):
        pass
    try:
        text = _SOURCE_CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return None
    return with_unreleased(text, unreleased_text(_SOURCE_ROOT / FRAGMENTS_DIR_NAME))


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


__all__ = [
    "CHANGELOG_NAME",
    "FRAGMENTS_DIR_NAME",
    "UNRELEASED",
    "changelog_text",
    "fragment_files",
    "history_markdown",
    "unreleased_text",
    "with_unreleased",
]
