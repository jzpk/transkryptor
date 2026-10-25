"""Strona projektu na GitHub Pages: opis, pobieranie i historia zmian.

Strona jest statyczna i powstaje przy każdym wydaniu (workflow „Strona”
wywoływany z „Wydania”), więc przyciski pobierania wskazują pliki najnowszego
wydania, a historia zmian obejmuje tylko wydane wersje — sekcja
„Nieopublikowane” nie trafia na stronę. Opis i wygląd są w katalogu
``pages/`` (szablony ``index.html`` i ``autor.html`` z polami ``${...}``,
arkusz stylów, skrypt motywu, zrzuty ekranu, zdjęcie autora i ikony); wymagania i nazwy plików pochodzą z ``packaging.metadata``,
tak jak w notach wydania.

    uv run python -m transkryptor.packaging.site --out _site
"""

from __future__ import annotations

import argparse
import html
import math
import random
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template

from transkryptor.packaging.changelog import (
    _HEADING,
    CHANGELOG_FILE,
    UNRELEASED,
    ChangelogError,
    _heading_key,
    section,
)
from transkryptor.packaging.metadata import (
    APP_NAME,
    HARDWARE_REQUIREMENTS,
    ICON_PNG,
    REPO_ROOT,
    SUMMARY,
    VERSION,
    targets,
)
from transkryptor.update.releases import GITHUB_REPO

AUTHOR_NAME = "Jeremiasz Pauszek"
LINKEDIN_URL = "https://www.linkedin.com/in/jeremiasz-pauszek-55a744213"

PAGES_DIR = REPO_ROOT / "pages"
TEMPLATE_FILE = "index.html"
# Strony z polami ${...}; pierwsza to strona główna.
TEMPLATE_FILES = (TEMPLATE_FILE, "autor.html")
# Pliki z pages/ kopiowane bez zmian (poza szablonami).
STATIC_FILES = ("style.css", "theme.js")
STATIC_DIRS = ("img",)

# Litery przelatujące w tle strony (efekt w style.css, klatki „fruwanie”).
# Losowane przy budowaniu ze stałym ziarnem, więc strona jest powtarzalna.
LETTERS = "aąbcćdeęfghijklłmnńoóprsśtuwyzźżĄĆĘŁŃÓŚŹŻ"
LETTER_COUNT = 44
_LETTERS_SEED = 2026

_VERSION_DATE = re.compile(r"^\d+\.\d+\.\d+\s+—\s+(?P<date>\d{4}-\d{2}-\d{2})$")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")

_MONTHS = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)


class SiteError(Exception):
    """Ze źródeł nie da się złożyć strony."""


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
        if version == UNRELEASED:
            continue
        dated = _VERSION_DATE.match(match["title"].strip())
        releases.append(
            Release(
                version=version,
                date=dated["date"] if dated else None,
                body=section(text, version) or "",
            )
        )
    return releases


def format_date(iso: str) -> str:
    """``2026-10-18`` → ``18 października 2026``."""
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{day} {_MONTHS[month - 1]} {year}"


def _inline(text: str) -> str:
    """``kod`` i **pogrubienie** z historii zmian jako HTML."""
    parts = []
    for index, chunk in enumerate(_CODE.split(text)):
        if index % 2:
            parts.append(f"<code>{html.escape(chunk)}</code>")
        else:
            parts.append(_BOLD.sub(r"<strong>\1</strong>", html.escape(chunk)))
    return "".join(parts)


def render_markdown(text: str) -> str:
    """HTML z podzbioru Markdown używanego w ``CHANGELOG.md``.

    Obsługuje akapity i płaskie listy ``- `` z wierszami kontynuacji oraz
    ``kod`` i **pogrubienie** w tekście.
    """
    blocks: list[str] = []
    items: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if items:
            rendered = "".join(f"<li>{_inline(item)}</li>" for item in items)
            blocks.append(f"<ul>{rendered}</ul>")
            items.clear()
        if paragraph:
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif raw.startswith("- "):
            if paragraph:
                flush()
            items.append(line[2:])
        elif items:
            items[-1] += " " + line
        else:
            paragraph.append(line)
    flush()
    return "\n".join(blocks)


def _changelog_html(releases: list[Release]) -> str:
    entries = []
    for index, release in enumerate(releases):
        when = (
            f' <time datetime="{release.date}">{format_date(release.date)}</time>'
            if release.date
            else ""
        )
        entries.append(
            f'<details class="release" id="v{release.version}"'
            f'{" open" if index == 0 else ""}>'
            f'<summary><span class="release-version">{release.version}</span>'
            f"{when}</summary>\n{render_markdown(release.body)}\n</details>"
        )
    return "\n".join(entries)


def _requirements_html() -> str:
    rows = "".join(
        f'<tr><th scope="row">{html.escape(item.resource)}</th>'
        f"<td>{html.escape(item.minimum)}</td>"
        f"<td>{html.escape(item.recommended)}</td></tr>"
        for item in HARDWARE_REQUIREMENTS
    )
    return (
        "<table><thead><tr><th>Zasób</th><th>Minimum</th><th>Zalecane</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _systems_html(version: str) -> str:
    return "".join(
        f"<li><strong>{html.escape(target.display_name)}</strong> — "
        f"{html.escape(target.baseline)}</li>"
        for target in targets(version).values()
    )


def letters_html(count: int = LETTER_COUNT, seed: int = _LETTERS_SEED) -> str:
    """Warstwa liter tła: każda leci po prostej przez cały ekran.

    Tor przechodzi przez losowy punkt ekranu w losowym kierunku; dłuższa
    składowa przesunięcia ma 120 jednostek (vw albo vh), więc oba końce toru
    leżą poza ekranem i powrót animacji na początek jest niewidoczny.
    """
    rng = random.Random(seed)
    spans = []
    for _ in range(count):
        letter = rng.choice(LETTERS)
        angle = rng.uniform(0, 2 * math.pi)
        dx, dy = math.cos(angle), math.sin(angle)
        scale = 120 / max(abs(dx), abs(dy))
        dx, dy = dx * scale, dy * scale
        cx, cy = rng.uniform(0, 100), rng.uniform(0, 100)
        duration = rng.uniform(35, 110)
        style = (
            f"--x0:{cx - dx:.1f};--y0:{cy - dy:.1f};"
            f"--x1:{cx + dx:.1f};--y1:{cy + dy:.1f};"
            f"--r0:{rng.randint(-180, 180)}deg;--r1:{rng.randint(-180, 180)}deg;"
            f"--s:{rng.uniform(1.5, 5):.2f}rem;"
            f"--t:{duration:.0f}s;--d:-{rng.uniform(0, duration):.0f}s"
        )
        spans.append(f'<span style="{style}">{letter}</span>')
    return f'<div class="letters" aria-hidden="true">{"".join(spans)}</div>'


def page_fields(releases: list[Release], repo: str) -> dict[str, str]:
    """Wartości pól szablonu dla najnowszego wydania."""
    if not releases:
        raise SiteError(f"{CHANGELOG_FILE.name} nie ma żadnej wydanej wersji.")
    latest = releases[0]
    version = latest.version
    repo_url = f"https://github.com/{repo}"
    download = f"{repo_url}/releases/download/v{version}"
    artifacts = targets(version)
    return {
        "app_name": APP_NAME,
        "summary": html.escape(SUMMARY),
        "version": version,
        "release_date": format_date(latest.date) if latest.date else "",
        "author_name": AUTHOR_NAME,
        "linkedin_url": LINKEDIN_URL,
        "profile_url": f"https://github.com/{repo.split('/')[0]}",
        "repo_url": repo_url,
        "releases_url": f"{repo_url}/releases",
        "release_url": f"{repo_url}/releases/tag/v{version}",
        "issues_url": f"{repo_url}/issues",
        "windows_url": f"{download}/{artifacts['windows'].artifact_name}",
        "windows_file": artifacts["windows"].artifact_name,
        "linux_url": f"{download}/{artifacts['linux'].artifact_name}",
        "linux_file": artifacts["linux"].artifact_name,
        # Instrukcja z taga wydania — ta w main może opisywać nowości,
        # których pobrana wersja jeszcze nie ma.
        "guide_url": f"{repo_url}/raw/v{version}/docs/user_guide_pl.pdf",
        "systems": _systems_html(version),
        "requirements": _requirements_html(),
        "changelog": _changelog_html(releases),
        "letters": letters_html(),
    }


def build(
    out: Path,
    changelog_file: Path = CHANGELOG_FILE,
    source: Path = PAGES_DIR,
    repo: str = GITHUB_REPO,
    expected_version: str | None = VERSION,
) -> Path:
    """Składa stronę w katalogu ``out`` i zwraca ścieżkę ``index.html``.

    ``expected_version`` pilnuje, żeby strona nie zapowiadała wersji innej niż
    ta w kodzie (np. przy budowaniu z gałęzi bez commita wydania).
    """
    try:
        text = Path(changelog_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ChangelogError(f"Brak pliku historii zmian: {changelog_file}.") from None
    releases = released_sections(text)
    fields = page_fields(releases, repo)
    if expected_version is not None and fields["version"] != expected_version:
        raise SiteError(
            f"Najnowsza wersja w {Path(changelog_file).name} ({fields['version']}) "
            f"różni się od wersji programu ({expected_version})."
        )
    pages = {}
    for name in TEMPLATE_FILES:
        template = Template((source / name).read_text(encoding="utf-8"))
        try:
            pages[name] = template.substitute(fields)
        except KeyError as error:
            raise SiteError(f"Szablon {name} używa nieznanego pola {error}.") from None
        except ValueError as error:
            raise SiteError(f"Błędne pole w szablonie {name}: {error}.") from None

    out.mkdir(parents=True, exist_ok=True)
    for name, page in pages.items():
        (out / name).write_text(page, encoding="utf-8")
    for name in STATIC_FILES:
        shutil.copy2(source / name, out / name)
    for name in STATIC_DIRS:
        shutil.copytree(source / name, out / name, dirs_exist_ok=True)
    shutil.copy2(ICON_PNG, out / "icon.png")
    return out / TEMPLATE_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.site", description=__doc__
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "_site",
        help="katalog wynikowy strony (domyślnie _site w repozytorium)",
    )
    args = parser.parse_args(argv)
    try:
        index = build(args.out)
    except (ChangelogError, SiteError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    print(index)
    return 0


__all__ = [
    "AUTHOR_NAME",
    "LETTERS",
    "LETTER_COUNT",
    "LINKEDIN_URL",
    "PAGES_DIR",
    "Release",
    "SiteError",
    "build",
    "format_date",
    "page_fields",
    "letters_html",
    "released_sections",
    "render_markdown",
]


if __name__ == "__main__":
    sys.exit(main())
