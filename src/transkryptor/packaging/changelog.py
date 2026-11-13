"""Historia zmian: źródło sekcji „Nowości w tej wersji” w notach wydania.

Zmiany widoczne dla użytkownika opisuje się razem z kodem w osobnych plikach
``changelog.d/<nazwa>.md`` (fragmentach, patrz ``transkryptor.changes``).
Workflow wydania składa je w sekcję wersji (``## X.Y.Z - RRRR-MM-DD``) nad
poprzednimi wersjami w ``CHANGELOG.md`` i usuwa pliki fragmentów, a noty
wydania przenoszą treść tej sekcji bez zmian. Brak fragmentów blokuje
wydanie: noty bez nowości byłyby kopią poprzednich.

Fragmenty zamiast jednej sekcji „Nieopublikowane” pozwalają szykować
poprawki na gałęzi ``release/X.Y`` równolegle z pracą na ``main``: scalenie
gałęzi wydania do ``main`` usuwa tylko fragmenty wydanej poprawki.

Moduł korzysta wyłącznie z biblioteki standardowej - workflow uruchamia go
przed instalacją zależności:

    PYTHONPATH=src python3 -m transkryptor.packaging.changelog release 0.2.4
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date as date_type
from pathlib import Path

from transkryptor.changes import FRAGMENTS_DIR_NAME, fragment_files, unreleased_text
from transkryptor.packaging.metadata import REPO_ROOT

CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"

_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")
_DATE_SUFFIX = re.compile(r"\s+-\s+.*$")


class ChangelogError(Exception):
    """Historia zmian nie pozwala złożyć not ani wydać wersji."""


def _heading_key(title: str) -> str:
    """Nagłówek bez daty: ``0.2.3 - 2026-10-09`` → ``0.2.3``."""
    return _DATE_SUFFIX.sub("", title.strip())


def _locate(lines: list[str], title: str) -> tuple[int, int] | None:
    """Indeks nagłówka sekcji i koniec jej treści (wyłącznie)."""
    start = None
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if not match:
            continue
        if start is not None:
            return start, index
        if _heading_key(match["title"]) == title:
            start = index
    return (start, len(lines)) if start is not None else None


def section(text: str, title: str) -> str | None:
    """Treść sekcji ``## <title>`` (np. wersji) lub None."""
    lines = text.splitlines()
    found = _locate(lines, title)
    if found is None:
        return None
    start, end = found
    return "\n".join(lines[start + 1 : end]).strip()


def fragments_dir(path: Path) -> Path:
    """Katalog fragmentów obok pliku historii zmian."""
    return Path(path).parent / FRAGMENTS_DIR_NAME


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ChangelogError(f"Brak pliku historii zmian: {path}.") from None


def whats_new(version: str, path: Path = CHANGELOG_FILE) -> str:
    """Nowości wersji do not wydania.

    Bez sekcji wersji (budowanie lokalne przed wydaniem) noty dostają treść
    fragmentów niewydanych zmian.
    """
    content = section(_read(path), version)
    if content is None:
        content = unreleased_text(fragments_dir(path))
    if not content:
        raise ChangelogError(
            f"{path} nie opisuje zmian wersji {version}: dodaj fragment "
            f"w {fragments_dir(path)}."
        )
    return content


def check(version: str, path: Path = CHANGELOG_FILE) -> str:
    """Treść sekcji wydanej wersji; błąd, gdy jej brak albo jest pusta."""
    content = section(_read(path), version)
    if not content:
        raise ChangelogError(f"{path} nie ma sekcji „## {version}” z opisem zmian.")
    return content


def release(
    version: str,
    release_date: date_type | None = None,
    path: Path = CHANGELOG_FILE,
) -> None:
    """Składa fragmenty w sekcję wersji nad poprzednimi i usuwa ich pliki."""
    lines = _read(path).splitlines()
    if _locate(lines, version) is not None:
        raise ChangelogError(f"{path} ma już sekcję wersji {version}.")
    directory = fragments_dir(path)
    content = unreleased_text(directory)
    if not content:
        raise ChangelogError(
            f"Brak fragmentów zmian w {directory} - opisz zmiany przed wydaniem."
        )
    when = release_date or date_type.today()
    index = next(
        (i for i, line in enumerate(lines) if _HEADING.match(line)), len(lines)
    )
    lines[index:index] = [f"## {version} - {when.isoformat()}", "", content, ""]
    Path(path).write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    for fragment in fragment_files(directory):
        fragment.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.changelog", description=__doc__
    )
    parser.add_argument(
        "command",
        choices=("release", "check"),
        help="release: złóż fragmenty zmian w sekcję wersji; "
        "check: sprawdź, że wersja ma opis zmian",
    )
    parser.add_argument("version", help="wersja w postaci X.Y.Z")
    parser.add_argument(
        "--file",
        type=Path,
        default=CHANGELOG_FILE,
        help="plik historii zmian (domyślnie CHANGELOG.md w repozytorium)",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "release":
            release(args.version, path=args.file)
        else:
            check(args.version, path=args.file)
    except ChangelogError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "CHANGELOG_FILE",
    "ChangelogError",
    "check",
    "fragments_dir",
    "release",
    "section",
    "whats_new",
]


if __name__ == "__main__":
    sys.exit(main())
