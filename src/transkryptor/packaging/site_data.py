"""Dane programu dla strony projektu (osobne repozytorium ``transkryptor-webpage``).

Generator strony nie importuje kodu programu: dostaje od niego plik JSON
z najnowszą wydaną wersją, historią zmian (tylko wydane wersje, bez
fragmentów ``changelog.d``), plikami do pobrania i wymaganiami sprzętowymi -
tymi samymi, co w notach wydania (``packaging.metadata``). Workflow strony
uruchamia moduł w checkoucie ``main`` tego repozytorium. Wystarcza
biblioteka standardowa:

    PYTHONPATH=src python3 -m transkryptor.packaging.site_data --out site-data.json

Format to kontrakt z repozytorium strony: zmiana znaczenia albo usunięcie
pola wymaga podbicia ``SCHEMA`` i dostosowania generatora strony. Nowe
pola można dopisywać bez zmiany ``SCHEMA``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from transkryptor.packaging.changelog import (
    _HEADING,
    CHANGELOG_FILE,
    ChangelogError,
    _heading_key,
    section,
)
from transkryptor.packaging.metadata import (
    APP_NAME,
    HARDWARE_REQUIREMENTS,
    LICENSE_ID,
    SUMMARY,
    VERSION,
    targets,
)

SCHEMA = 1

_VERSION_DATE = re.compile(r"^\d+\.\d+\.\d+\s+-\s+(?P<date>\d{4}-\d{2}-\d{2})$")


class SiteDataError(Exception):
    """Z historii zmian nie da się złożyć danych strony."""


@dataclass(frozen=True)
class Release:
    """Wydana wersja z historii zmian."""

    version: str
    date: str | None
    body: str


def released_sections(text: str) -> list[Release]:
    """Wydane wersje w kolejności z pliku (najnowsza pierwsza)."""
    releases = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if not match:
            continue
        version = _heading_key(match["title"])
        dated = _VERSION_DATE.match(match["title"].strip())
        releases.append(
            Release(
                version=version,
                date=dated["date"] if dated else None,
                body=section(text, version) or "",
            )
        )
    return releases


def site_data(changelog: str, version: str = VERSION) -> dict[str, object]:
    """Dane strony dla najnowszego wydania z historii zmian ``changelog``.

    ``version`` pilnuje, żeby strona nie zapowiadała wersji innej niż ta
    w kodzie (np. przy danych z gałęzi bez commita wydania).
    """
    releases = released_sections(changelog)
    if not releases:
        raise SiteDataError(f"{CHANGELOG_FILE.name} nie ma żadnej wydanej wersji.")
    latest = releases[0].version
    if latest != version:
        raise SiteDataError(
            f"Najnowsza wersja w {CHANGELOG_FILE.name} ({latest}) "
            f"różni się od wersji programu ({version})."
        )
    return {
        "schema": SCHEMA,
        "app_name": APP_NAME,
        "summary": SUMMARY,
        "license_id": LICENSE_ID,
        "version": latest,
        "releases": [asdict(release) for release in releases],
        "downloads": {
            key: {
                "display_name": target.display_name,
                "file": target.artifact_name,
                "baseline": target.baseline,
            }
            for key, target in targets(latest).items()
        },
        "requirements": [
            {
                "resource": item.resource,
                "minimum": item.minimum,
                "recommended": item.recommended,
            }
            for item in HARDWARE_REQUIREMENTS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.site_data", description=__doc__
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="plik wynikowy JSON z danymi strony"
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=CHANGELOG_FILE,
        help="historia zmian (domyślnie CHANGELOG.md w repozytorium)",
    )
    args = parser.parse_args(argv)
    try:
        try:
            text = args.changelog.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ChangelogError(
                f"Brak pliku historii zmian: {args.changelog}."
            ) from None
        data = site_data(text)
    except (ChangelogError, SiteDataError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.out)
    return 0


__all__ = [
    "SCHEMA",
    "Release",
    "SiteDataError",
    "main",
    "released_sections",
    "site_data",
]


if __name__ == "__main__":
    sys.exit(main())
