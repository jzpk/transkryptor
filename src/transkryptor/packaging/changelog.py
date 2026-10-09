"""Historia zmian: źródło sekcji „Nowości w tej wersji” w notach wydania.

Zmiany widoczne dla użytkownika dopisuje się w ``CHANGELOG.md`` w sekcji
„Nieopublikowane”, razem z kodem. Workflow wydania zamienia ją na sekcję
wersji (``## X.Y.Z — RRRR-MM-DD``), a noty wydania przenoszą treść tej sekcji
bez zmian. Pusta sekcja blokuje wydanie: noty bez nowości byłyby kopią
poprzednich.

Moduł korzysta wyłącznie z biblioteki standardowej — workflow uruchamia go
przed instalacją zależności:

    PYTHONPATH=src python3 -m transkryptor.packaging.changelog release 0.2.4
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date as date_type
from pathlib import Path

from transkryptor.packaging.metadata import REPO_ROOT

CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
UNRELEASED = "Nieopublikowane"

_HEADING = re.compile(r"^## (?P<title>.+?)\s*$")
_DATE_SUFFIX = re.compile(r"\s+—\s+.*$")


class ChangelogError(Exception):
    """Historia zmian nie pozwala złożyć not ani wydać wersji."""


def _heading_key(title: str) -> str:
    """Nagłówek bez daty: ``0.2.3 — 2026-10-09`` → ``0.2.3``."""
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
    """Treść sekcji ``## <title>`` (wersji albo „Nieopublikowane”) lub None."""
    lines = text.splitlines()
    found = _locate(lines, title)
    if found is None:
        return None
    start, end = found
    return "\n".join(lines[start + 1 : end]).strip()


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ChangelogError(f"Brak pliku historii zmian: {path}.") from None


def whats_new(version: str, path: Path = CHANGELOG_FILE) -> str:
    """Nowości wersji do not wydania.

    Bez sekcji wersji (budowanie lokalne przed wydaniem) noty dostają treść
    „Nieopublikowane”.
    """
    text = _read(path)
    content = section(text, version)
    if content is None:
        content = section(text, UNRELEASED)
    if not content:
        raise ChangelogError(
            f"{path} nie opisuje zmian wersji {version}: dopisz je w sekcji "
            f"„{UNRELEASED}”."
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
    """Zamienia „Nieopublikowane” na sekcję wersji i otwiera nową, pustą."""
    text = _read(path)
    lines = text.splitlines()
    if _locate(lines, version) is not None:
        raise ChangelogError(f"{path} ma już sekcję wersji {version}.")
    found = _locate(lines, UNRELEASED)
    if found is None:
        raise ChangelogError(f"{path} nie ma sekcji „## {UNRELEASED}”.")
    start, end = found
    if not "\n".join(lines[start + 1 : end]).strip():
        raise ChangelogError(
            f"Sekcja „{UNRELEASED}” w {path} jest pusta — opisz zmiany "
            "przed wydaniem."
        )
    when = release_date or date_type.today()
    lines[start : start + 1] = [
        f"## {UNRELEASED}",
        "",
        f"## {version} — {when.isoformat()}",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.changelog", description=__doc__
    )
    parser.add_argument(
        "command",
        choices=("release", "check"),
        help="release: nadaj sekcji „Nieopublikowane” numer wersji; "
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
    "UNRELEASED",
    "ChangelogError",
    "check",
    "release",
    "section",
    "whats_new",
]


if __name__ == "__main__":
    sys.exit(main())
