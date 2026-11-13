"""Etykiety zgłoszeń: kiedy zrobiona zmiana trafiła do użytkowników.

Zgłoszenia programu i strony projektu docierają do użytkowników inną drogą,
więc dostają inne etykiety (tryb wywołania):

- ``release X.Y.Z`` - po publikacji wydania workflow „Wydanie” nadaje
  etykietę z numerem wersji (``0.8.0``) zgłoszeniom zamkniętym jako zrobione
  (``state_reason`` „completed”) przed granicą, bez etykiety żadnej wersji.
  Pomija zgłoszenia z etykietą ``webpage`` - strona nie czeka na wydanie.
- ``site`` - po wdrożeniu strony workflow „Strona” nadaje etykietę
  ``wdrożone`` zrobionym zgłoszeniom z etykietą ``webpage``, które jej
  jeszcze nie mają.

Wydania i strona powstają z ``main``, więc zamknięte zgłoszenie jest już
w kodzie najbliższego wydania albo wdrożenia. Strona statusu zgłoszeń
(``pages/site.js``) pokazuje wersję albo „Wdrożone”, a zrobione zgłoszenie
bez etykiety - jako niewydane albo niewdrożone.

Granicą (``--cutoff``) jest chwila publikacji wydania albo początek
wdrożenia strony, a nie data commita: commit bywa starszy niż zamknięcie
zgłoszenia przy pushu. Zgłoszenie zamknięte w trakcie budowania dostanie
etykietę za wcześnie - wtedy poprawia się ją ręcznie na GitHubie. Ponowne
uruchomienie nie zmienia już oznaczonych zgłoszeń.

Moduł korzysta wyłącznie z biblioteki standardowej - workflow uruchamia go
bez instalacji zależności. Repozytorium i token biorą się ze zmiennych
``GITHUB_REPOSITORY`` i ``GH_TOKEN``:

    PYTHONPATH=src python3 -m transkryptor.packaging.issue_labels \\
        release 0.8.0 --cutoff 2026-11-20T12:00:00Z
    PYTHONPATH=src python3 -m transkryptor.packaging.issue_labels \\
        site --cutoff 2026-11-21T08:00:00Z
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

VERSION_LABEL_RE = re.compile(r"^v?\d+\.\d+\.\d+$")
WEBPAGE_LABEL = "webpage"
DEPLOYED_LABEL = "wdrożone"
LABEL_COLOR = "2da44e"
API_URL = "https://api.github.com"

_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')

Issue = dict[str, Any]


class LabelError(Exception):
    """Nie udało się odczytać zgłoszeń ani nadać etykiet."""


@dataclass(frozen=True)
class Target:
    """Etykieta do nadania i zgłoszenia, których dotyczy."""

    label: str
    description: str
    webpage: bool  # True: tylko zgłoszenia strony, False: tylko programu

    def applies_to(self, labels: list[str]) -> bool:
        """Czy zgłoszenie z etykietami ``labels`` ma dostać tę etykietę."""
        names = [name.lower() for name in labels]
        if (WEBPAGE_LABEL in names) != self.webpage:
            return False
        if self.webpage:
            return DEPLOYED_LABEL not in names
        return not any(is_version_label(name) for name in names)


def release_target(version: str) -> Target:
    """Etykieta wersji programu dla zgłoszeń bez etykiety ``webpage``."""
    if not is_version_label(version) or version.startswith("v"):
        raise LabelError(f"Wersja musi mieć postać X.Y.Z (podano: {version}).")
    return Target(version, "Wydane w tej wersji programu", webpage=False)


SITE_TARGET = Target(DEPLOYED_LABEL, "Wdrożone na stronie projektu", webpage=True)


class IssueTracker(Protocol):
    """Operacje na zgłoszeniach repozytorium potrzebne do nadania etykiet."""

    def closed_issues(self) -> Iterable[Issue]: ...

    def ensure_label(self, name: str, description: str) -> None: ...

    def add_label(self, number: int, name: str) -> None: ...


def is_version_label(name: str) -> bool:
    """Czy etykieta to numer wersji (``0.8.0`` albo ``v0.8.0``)."""
    return bool(VERSION_LABEL_RE.match(name))


def _parse_time(value: str) -> datetime:
    """Czas ISO 8601; bez strefy czasowej przyjmuje UTC (jak API GitHuba)."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # timezone.utc, bo workflow uruchamia moduł systemowym Pythonem 3.10.
    utc = timezone.utc  # noqa: UP017 - datetime.UTC dopiero od Pythona 3.11
    return moment if moment.tzinfo else moment.replace(tzinfo=utc)


def _label_names(issue: Issue) -> list[str]:
    return [
        label if isinstance(label, str) else str(label.get("name", ""))
        for label in issue.get("labels") or []
    ]


def _done_before(issue: Issue, cutoff: datetime) -> bool:
    """Zgłoszenie (nie PR) zamknięte jako zrobione nie później niż ``cutoff``."""
    if issue.get("pull_request") or issue.get("state") != "closed":
        return False
    if issue.get("state_reason") != "completed" or not issue.get("closed_at"):
        return False
    return _parse_time(issue["closed_at"]) <= cutoff


def issues_to_label(
    issues: Iterable[Issue], target: Target, cutoff: datetime
) -> list[int]:
    """Numery zrobionych zgłoszeń sprzed ``cutoff``, którym brakuje etykiety."""
    return sorted(
        int(issue["number"])
        for issue in issues
        if _done_before(issue, cutoff) and target.applies_to(_label_names(issue))
    )


class GitHubIssues:
    """Zgłoszenia repozytorium przez REST API GitHuba."""

    def __init__(self, repository: str, token: str, api_url: str = API_URL) -> None:
        if not api_url.startswith("https://"):
            raise LabelError(f"Adres API musi używać https: {api_url}.")
        self._base = f"{api_url}/repos/{repository}"
        self._token = token

    def _request(
        self, method: str, url: str, body: object | None = None
    ) -> tuple[Any, str]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        # Adresy pochodzą z api_url (sprawdzone https) albo z nagłówka Link API.
        request = urllib.request.Request(  # noqa: S310 - tylko https API GitHuba
            url, data=data, method=method
        )
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(  # noqa: S310 - tylko https API GitHuba
            request, timeout=30
        ) as response:
            payload = response.read()
            link = response.headers.get("Link") or ""
        return (json.loads(payload) if payload else None), link

    def closed_issues(self) -> Iterator[Issue]:
        url: str | None = f"{self._base}/issues?state=closed&per_page=100"
        while url:
            issues, link = self._request("GET", url)
            yield from issues
            match = _NEXT_LINK.search(link)
            url = match.group(1) if match else None

    def ensure_label(self, name: str, description: str) -> None:
        body = {"name": name, "color": LABEL_COLOR, "description": description}
        try:
            self._request("POST", f"{self._base}/labels", body)
        except urllib.error.HTTPError as error:
            # 422: etykieta już istnieje (np. ponowne uruchomienie joba).
            if error.code != 422:
                raise

    def add_label(self, number: int, name: str) -> None:
        self._request(
            "POST", f"{self._base}/issues/{number}/labels", {"labels": [name]}
        )


def label_issues(
    tracker: IssueTracker, target: Target, cutoff: datetime, *, dry_run: bool = False
) -> list[int]:
    """Nadaje etykietę ``target`` zgłoszeniom zrobionym przed ``cutoff``."""
    numbers = issues_to_label(tracker.closed_issues(), target, cutoff)
    if numbers and not dry_run:
        tracker.ensure_label(target.label, target.description)
        for number in numbers:
            tracker.add_label(number, target.label)
    return numbers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.issue_labels",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    release = modes.add_parser("release", help="etykieta wersji programu")
    release.add_argument("version", help="wersja w postaci X.Y.Z")
    site = modes.add_parser("site", help=f"etykieta „{DEPLOYED_LABEL}” zgłoszeń strony")
    for mode in (release, site):
        mode.add_argument(
            "--cutoff",
            required=True,
            type=_parse_time,
            help="publikacja wydania albo początek wdrożenia strony (ISO 8601)",
        )
        mode.add_argument(
            "--dry-run", action="store_true", help="tylko wypisz, nic nie zmieniaj"
        )
    return parser


def _tracker_from_env() -> IssueTracker:
    repository = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_TOKEN")
    if not repository or not token:
        raise LabelError("Brak zmiennych GITHUB_REPOSITORY albo GH_TOKEN.")
    return GitHubIssues(repository, token)


def main(argv: list[str] | None = None, tracker: IssueTracker | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        target = release_target(args.version) if args.mode == "release" else SITE_TARGET
        numbers = label_issues(
            tracker or _tracker_from_env(), target, args.cutoff, dry_run=args.dry_run
        )
    except (LabelError, urllib.error.URLError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    verb = "Do oznaczenia" if args.dry_run else "Oznaczone"
    listed = ", ".join(f"#{number}" for number in numbers) or "brak"
    print(f"{verb} etykietą {target.label}: {listed}")
    return 0


__all__ = [
    "DEPLOYED_LABEL",
    "SITE_TARGET",
    "WEBPAGE_LABEL",
    "GitHubIssues",
    "IssueTracker",
    "LabelError",
    "Target",
    "is_version_label",
    "issues_to_label",
    "label_issues",
    "main",
    "release_target",
]


if __name__ == "__main__":
    sys.exit(main())
