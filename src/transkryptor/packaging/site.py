"""Strona projektu na GitHub Pages: opis, pobieranie, historia zmian i FAQ.

Strona jest statyczna i powstaje przy każdym wydaniu (workflow „Strona”
wywoływany z „Wydania”), więc przyciski pobierania wskazują pliki najnowszego
wydania, a historia zmian obejmuje tylko wydane wersje - sekcja
„Nieopublikowane” nie trafia na stronę. Opis i wygląd są w katalogu
``pages/`` (szablony ``index.html``, ``faq.html``, ``autor.html`` i ``404.html``
z polami ``${...}``, formularz zgłoszeń ``zglos.html``, status zgłoszeń
``zgloszenia.html``, arkusz stylów, skrypt strony, zrzuty ekranu, zdjęcie autora
i ikony); wymagania i nazwy plików pochodzą z ``packaging.metadata``,
tak jak w notach wydania. Dla wyszukiwarek generator dodaje ``sitemap.xml``,
``robots.txt`` i dane strukturalne schema.org (JSON-LD) w nagłówkach stron.

    uv run python -m transkryptor.packaging.site --out _site
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import random
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Template

from transkryptor.feedback import REPORT_PAGE, SITE_URL
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
    LICENSE_ID,
    REPO_ROOT,
    SUMMARY,
    VERSION,
    targets,
)
from transkryptor.update.releases import GITHUB_REPO

AUTHOR_NAME = "Jeremiasz Pauszek"
LINKEDIN_URL = "https://www.linkedin.com/in/jeremiasz-pauszek-55a744213"
# Formularz zgłoszeń wysyła dane do Workera Cloudflare (katalog zgloszenia/),
# a ten zakłada issue na GitHubie. Adres Workera i publiczny klucz Turnstile
# (ochrona przed botami) podaje workflow „Strona” ze zmiennych repozytorium;
# bez nich formularz odsyła do zgłoszeń na GitHubie.
REPORT_ENDPOINT_ENV = "TRANSKRYPTOR_REPORT_ENDPOINT"
TURNSTILE_SITE_KEY_ENV = "TRANSKRYPTOR_TURNSTILE_SITE_KEY"

PAGES_DIR = REPO_ROOT / "pages"
# Status zgłoszeń: skrypt strony pobiera listę z publicznego API GitHuba
# (bez tokenu, więc strona może pokazać najwyżej 100 ostatnio zmienionych).
ISSUES_PAGE = "zgloszenia.html"
GITHUB_API = "https://api.github.com"
TEMPLATE_FILE = "index.html"
# Strony z polami ${...}; pierwsza to strona główna.
TEMPLATE_FILES = (
    TEMPLATE_FILE,
    "faq.html",
    "autor.html",
    REPORT_PAGE,
    ISSUES_PAGE,
    "404.html",
)
# Strony w mapie strony; 404.html ma noindex.
INDEXED_FILES = tuple(name for name in TEMPLATE_FILES if name != "404.html")
SITEMAP_FILE = "sitemap.xml"
ROBOTS_FILE = "robots.txt"
# Pliki z pages/ kopiowane bez zmian (poza szablonami).
STATIC_FILES = ("style.css", "site.js")
STATIC_DIRS = ("img",)

# Litery przelatujące w tle strony (efekt w style.css, klatki „fruwanie”).
# Losowane przy budowaniu ze stałym ziarnem, więc strona jest powtarzalna.
LETTERS = "aąbcćdeęfghijklłmnńoóprsśtuwyzźżĄĆĘŁŃÓŚŹŻ"
LETTER_COUNT = 44
_LETTERS_SEED = 2026

_VERSION_DATE = re.compile(r"^\d+\.\d+\.\d+\s+-\s+(?P<date>\d{4}-\d{2}-\d{2})$")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
# Pytanie z faq.html: <summary> to pytanie, <div class="faq-answer"> odpowiedź.
_FAQ_ITEM = re.compile(
    r'<details class="faq-item" id="[^"]+">\s*<summary>(?P<question>.*?)</summary>'
    r'\s*<div class="faq-answer">(?P<answer>.*?)</div>\s*</details>',
    re.DOTALL,
)
_BLOCK_TAG = re.compile(r"</?(?:p|ul|ol|li|pre|br)\b[^>]*>")
_TAG = re.compile(r"<[^>]+>")

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
    for release in releases:
        when = (
            f' <time datetime="{release.date}">{format_date(release.date)}</time>'
            if release.date
            else ""
        )
        entries.append(
            f'<details class="release" id="v{release.version}">'
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
        f"<li><strong>{html.escape(target.display_name)}</strong> - "
        f"{html.escape(target.baseline)}</li>"
        for target in targets(version).values()
    )


def background_letters(
    count: int = LETTER_COUNT, seed: int = _LETTERS_SEED
) -> tuple[str, str]:
    """Warstwa liter tła (HTML) i klatki ich animacji (CSS).

    Każda litera leci po prostej przez cały ekran. Tor przechodzi przez losowy
    punkt ekranu w losowym kierunku; dłuższa składowa przesunięcia ma 120
    jednostek (vw albo vh), więc oba końce toru leżą poza ekranem i powrót
    animacji na początek jest niewidoczny. Każda litera ma własne klatki
    ze stałymi wartościami - klatki ze zmiennymi CSS przeglądarka może
    liczyć w wątku głównym zamiast na GPU, co daje przycięcia ruchu.
    """
    rng = random.Random(seed)
    spans = []
    keyframes = []
    for index in range(count):
        letter = rng.choice(LETTERS)
        angle = rng.uniform(0, 2 * math.pi)
        dx, dy = math.cos(angle), math.sin(angle)
        scale = 120 / max(abs(dx), abs(dy))
        dx, dy = dx * scale, dy * scale
        cx, cy = rng.uniform(0, 100), rng.uniform(0, 100)
        r0, r1 = rng.randint(-180, 180), rng.randint(-180, 180)
        size = rng.uniform(1.5, 5)
        duration = rng.uniform(35, 110)
        delay = rng.uniform(0, duration)
        name = f"litera-{index}"
        keyframes.append(
            f"@keyframes {name}{{"
            f"from{{transform:translate({cx - dx:.1f}vw,{cy - dy:.1f}vh)"
            f" rotate({r0}deg)}}"
            f"to{{transform:translate({cx + dx:.1f}vw,{cy + dy:.1f}vh)"
            f" rotate({r1}deg)}}}}"
        )
        # Bez skrótu ``animation``: ustawiłby też animation-play-state
        # w stylu inline, którego przełącznik animacji z arkusza nie nadpisze.
        style = (
            f"font-size:{size:.2f}rem;animation-name:{name};"
            f"animation-duration:{duration:.0f}s;animation-delay:-{delay:.0f}s"
        )
        spans.append(f'<span style="{style}">{letter}</span>')
    layer = f'<div class="letters" aria-hidden="true">{"".join(spans)}</div>'
    return layer, "\n".join(keyframes)


def page_fields(
    releases: list[Release],
    repo: str,
    report_endpoint: str = "",
    turnstile_site_key: str = "",
) -> dict[str, str]:
    """Wartości pól szablonu dla najnowszego wydania."""
    if not releases:
        raise SiteError(f"{CHANGELOG_FILE.name} nie ma żadnej wydanej wersji.")
    latest = releases[0]
    version = latest.version
    repo_url = f"https://github.com/{repo}"
    download = f"{repo_url}/releases/download/v{version}"
    artifacts = targets(version)
    letters, letters_css = background_letters()
    return {
        "app_name": APP_NAME,
        "summary": html.escape(SUMMARY),
        "version": version,
        "release_date": format_date(latest.date) if latest.date else "",
        "release_date_iso": latest.date or "",
        "author_name": AUTHOR_NAME,
        "linkedin_url": LINKEDIN_URL,
        "site_url": SITE_URL,
        "profile_url": f"https://github.com/{repo.split('/')[0]}",
        "repo_url": repo_url,
        "releases_url": f"{repo_url}/releases",
        "release_url": f"{repo_url}/releases/tag/v{version}",
        "issues_url": f"{repo_url}/issues",
        "issues_api_url": html.escape(
            f"{GITHUB_API}/repos/{repo}/issues?state=all&sort=updated&per_page=100"
        ),
        "report_endpoint": html.escape(report_endpoint),
        "turnstile_site_key": html.escape(turnstile_site_key),
        "windows_url": f"{download}/{artifacts['windows'].artifact_name}",
        "windows_file": artifacts["windows"].artifact_name,
        "linux_url": f"{download}/{artifacts['linux'].artifact_name}",
        "linux_file": artifacts["linux"].artifact_name,
        # Instrukcja z taga wydania - ta w main może opisywać nowości,
        # których pobrana wersja jeszcze nie ma.
        "guide_url": f"{repo_url}/raw/v{version}/docs/user_guide_pl.pdf",
        "systems": _systems_html(version),
        "requirements": _requirements_html(),
        "changelog": _changelog_html(releases),
        "letters": letters,
        "letters_css": letters_css,
    }


def page_url(name: str) -> str:
    """Adres kanoniczny strony: ``index.html`` → ``https://…/``."""
    return f"{SITE_URL}/" if name == TEMPLATE_FILE else f"{SITE_URL}/{name}"


def sitemap(lastmod: str | None) -> str:
    """Mapa strony z adresami kanonicznymi; ``lastmod`` to data wydania."""
    when = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    urls = "".join(
        f"  <url><loc>{page_url(name)}</loc>{when}</url>\n" for name in INDEXED_FILES
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    )


def robots() -> str:
    """``robots.txt``: wszystko do indeksowania, z adresem mapy strony."""
    return f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/{SITEMAP_FILE}\n"


def _plain(fragment: str) -> str:
    """Tekst fragmentu HTML w jednym wierszu (bez znaczników i encji)."""
    text = _TAG.sub("", _BLOCK_TAG.sub(" ", fragment))
    return " ".join(html.unescape(text).split())


def faq_questions(page: str) -> list[tuple[str, str]]:
    """Pary (pytanie, odpowiedź) jako zwykły tekst ze złożonej strony FAQ."""
    return [
        (_plain(match["question"]), _plain(match["answer"]))
        for match in _FAQ_ITEM.finditer(page)
    ]


def structured_data(name: str, page: str, fields: dict[str, str]) -> dict | None:
    """Dane schema.org dla strony ``name`` albo ``None``, gdy ich nie ma.

    FAQ powstaje z treści złożonej strony, więc pytania nie są powielane
    w dwóch miejscach.
    """
    author = {
        "@type": "Person",
        "name": AUTHOR_NAME,
        "url": page_url("autor.html"),
    }
    if name == TEMPLATE_FILE:
        program: dict[str, object] = {
            "@type": "SoftwareApplication",
            "name": APP_NAME,
            "description": f"{SUMMARY}.",
            "url": page_url(name),
            "applicationCategory": "UtilitiesApplication",
            "operatingSystem": "Windows 10, Windows 11, Linux",
            "softwareVersion": fields["version"],
            "inLanguage": "pl",
            "isAccessibleForFree": True,
            "license": f"https://spdx.org/licenses/{LICENSE_ID}.html",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "PLN"},
            "downloadUrl": [fields["windows_url"], fields["linux_url"]],
            "screenshot": f"{SITE_URL}/img/okno-szkic-asr.webp",
            "image": f"{SITE_URL}/img/podglad.jpg",
            "softwareHelp": {"@type": "CreativeWork", "url": fields["guide_url"]},
            "author": author,
            "sameAs": [fields["repo_url"]],
        }
        if fields["release_date_iso"]:
            program["datePublished"] = fields["release_date_iso"]
        return {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "WebSite",
                    "name": APP_NAME,
                    "url": page_url(name),
                    "inLanguage": "pl",
                },
                program,
            ],
        }
    if name == "faq.html":
        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": question,
                    "acceptedAnswer": {"@type": "Answer", "text": answer},
                }
                for question, answer in faq_questions(page)
            ],
        }
    if name == "autor.html":
        return {
            "@context": "https://schema.org",
            "@type": "ProfilePage",
            "url": page_url(name),
            "mainEntity": author
            | {
                "image": f"{SITE_URL}/img/autor.jpg",
                "sameAs": [fields["linkedin_url"], fields["profile_url"]],
            },
        }
    return None


def add_structured_data(page: str, data: dict) -> str:
    """Wstawia blok JSON-LD na koniec ``<head>``.

    ``</`` jest zamaskowane, żeby tekst z danymi nie zamknął znacznika skryptu.
    """
    text = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    block = f'  <script type="application/ld+json">\n{text}\n    </script>\n'
    return page.replace("  </head>", f"  {block}  </head>", 1)


def build(
    out: Path,
    changelog_file: Path = CHANGELOG_FILE,
    source: Path = PAGES_DIR,
    repo: str = GITHUB_REPO,
    expected_version: str | None = VERSION,
    report_endpoint: str | None = None,
    turnstile_site_key: str | None = None,
) -> Path:
    """Składa stronę w katalogu ``out`` i zwraca ścieżkę ``index.html``.

    ``expected_version`` pilnuje, żeby strona nie zapowiadała wersji innej niż
    ta w kodzie (np. przy budowaniu z gałęzi bez commita wydania). Adres
    Workera zgłoszeń i klucz Turnstile domyślnie pochodzą ze zmiennych
    środowiska ``TRANSKRYPTOR_REPORT_ENDPOINT`` i
    ``TRANSKRYPTOR_TURNSTILE_SITE_KEY``.
    """
    try:
        text = Path(changelog_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ChangelogError(f"Brak pliku historii zmian: {changelog_file}.") from None
    releases = released_sections(text)
    if report_endpoint is None:
        report_endpoint = os.environ.get(REPORT_ENDPOINT_ENV, "").strip()
    if turnstile_site_key is None:
        turnstile_site_key = os.environ.get(TURNSTILE_SITE_KEY_ENV, "").strip()
    if report_endpoint and not report_endpoint.startswith("https://"):
        raise SiteError("Adres Workera zgłoszeń musi zaczynać się od https://.")
    fields = page_fields(releases, repo, report_endpoint, turnstile_site_key)
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
        data = structured_data(name, pages[name], fields)
        if data is not None:
            pages[name] = add_structured_data(pages[name], data)

    out.mkdir(parents=True, exist_ok=True)
    for name, page in pages.items():
        (out / name).write_text(page, encoding="utf-8")
    (out / SITEMAP_FILE).write_text(
        sitemap(fields["release_date_iso"] or None), encoding="utf-8"
    )
    (out / ROBOTS_FILE).write_text(robots(), encoding="utf-8")
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
    "INDEXED_FILES",
    "ISSUES_PAGE",
    "LETTERS",
    "LETTER_COUNT",
    "LINKEDIN_URL",
    "PAGES_DIR",
    "REPORT_ENDPOINT_ENV",
    "ROBOTS_FILE",
    "SITEMAP_FILE",
    "SITE_URL",
    "TURNSTILE_SITE_KEY_ENV",
    "Release",
    "SiteError",
    "add_structured_data",
    "build",
    "faq_questions",
    "format_date",
    "page_fields",
    "page_url",
    "background_letters",
    "released_sections",
    "render_markdown",
    "robots",
    "sitemap",
    "structured_data",
]


if __name__ == "__main__":
    sys.exit(main())
