"""Etykiety wersji w zgłoszeniach: w którym wydaniu trafiły do programu.

Po publikacji wydania workflow nadaje etykietę z numerem wersji (``0.8.0``)
każdemu zgłoszeniu zamkniętemu jako zrobione (``state_reason`` „completed”)
przed chwilą publikacji, które nie ma jeszcze etykiety żadnej wersji.
Wydania powstają zawsze z ``main``, więc zamknięte zgłoszenie jest już
w kodzie najbliższej wersji. Strona statusu zgłoszeń (``pages/site.js``)
pokazuje wersję z etykiety, a zrobione zgłoszenie bez niej - jako niewydane.

Granicą jest chwila publikacji wydania, a nie data commita taga: w drodze
awaryjnej (ręcznie wypchnięty tag) commit bywa starszy niż zamknięcie
zgłoszenia przy pushu. Zgłoszenie zamknięte w trakcie budowania wydania
dostanie etykietę tej wersji, choć trafi dopiero do następnej - wtedy
etykietę poprawia się ręcznie na GitHubie. Ponowne uruchomienie nie zmienia
już oznaczonych zgłoszeń.

Moduł korzysta wyłącznie z biblioteki standardowej - workflow uruchamia go
bez instalacji zależności. Repozytorium i token biorą się ze zmiennych
``GITHUB_REPOSITORY`` i ``GH_TOKEN``:

    PYTHONPATH=src python3 -m transkryptor.packaging.issue_labels 0.8.0 \\
        --cutoff 2026-11-20T12:00:00Z
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
from datetime import datetime, timezone
from typing import Any, Protocol

VERSION_LABEL_RE = re.compile(r"^v?\d+\.\d+\.\d+$")
LABEL_COLOR = "2da44e"
LABEL_DESCRIPTION = "Wydane w tej wersji programu"
API_URL = "https://api.github.com"

_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')

Issue = dict[str, Any]


class LabelError(Exception):
    """Nie udało się odczytać zgłoszeń ani nadać etykiet."""


class IssueTracker(Protocol):
    """Operacje na zgłoszeniach repozytorium potrzebne do nadania etykiet."""

    def closed_issues(self) -> Iterable[Issue]: ...

    def ensure_label(self, name: str) -> None: ...

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


def issues_to_label(issues: Iterable[Issue], cutoff: datetime) -> list[int]:
    """Numery zrobionych zgłoszeń sprzed ``cutoff`` bez etykiety wersji."""
    numbers = []
    for issue in issues:
        if issue.get("pull_request") or issue.get("state") != "closed":
            continue
        if issue.get("state_reason") != "completed" or not issue.get("closed_at"):
            continue
        if _parse_time(issue["closed_at"]) > cutoff:
            continue
        if any(is_version_label(name) for name in _label_names(issue)):
            continue
        numbers.append(int(issue["number"]))
    return sorted(numbers)


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

    def ensure_label(self, name: str) -> None:
        body = {"name": name, "color": LABEL_COLOR, "description": LABEL_DESCRIPTION}
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


def label_release(
    tracker: IssueTracker, version: str, cutoff: datetime, *, dry_run: bool = False
) -> list[int]:
    """Nadaje etykietę ``version`` zgłoszeniom zrobionym przed ``cutoff``."""
    if not is_version_label(version) or version.startswith("v"):
        raise LabelError(f"Wersja musi mieć postać X.Y.Z (podano: {version}).")
    numbers = issues_to_label(tracker.closed_issues(), cutoff)
    if numbers and not dry_run:
        tracker.ensure_label(version)
        for number in numbers:
            tracker.add_label(number, version)
    return numbers


def main(argv: list[str] | None = None, tracker: IssueTracker | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging.issue_labels", description=__doc__
    )
    parser.add_argument("version", help="wersja w postaci X.Y.Z")
    parser.add_argument(
        "--cutoff",
        required=True,
        type=_parse_time,
        help="chwila publikacji wydania (ISO 8601, np. 2026-11-20T12:00:00Z)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="tylko wypisz, nic nie zmieniaj"
    )
    args = parser.parse_args(argv)
    try:
        if tracker is None:
            repository = os.environ.get("GITHUB_REPOSITORY")
            token = os.environ.get("GH_TOKEN")
            if not repository or not token:
                raise LabelError("Brak zmiennych GITHUB_REPOSITORY albo GH_TOKEN.")
            tracker = GitHubIssues(repository, token)
        numbers = label_release(
            tracker, args.version, args.cutoff, dry_run=args.dry_run
        )
    except (LabelError, urllib.error.URLError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    verb = "Do oznaczenia" if args.dry_run else "Oznaczone"
    listed = ", ".join(f"#{number}" for number in numbers) or "brak"
    print(f"{verb} etykietą {args.version}: {listed}")
    return 0


__all__ = [
    "GitHubIssues",
    "IssueTracker",
    "LabelError",
    "is_version_label",
    "issues_to_label",
    "label_release",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
