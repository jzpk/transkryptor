"""Migracje schematu pliku projektu do bieżącej wersji.

Nowa wersja schematu to podbicie ``SCHEMA_VERSION`` i nowy wpis
w ``_MIGRATIONS``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from transkryptor.document.project.errors import invalid
from transkryptor.document.speakers import DEFAULT_SPEAKERS
from transkryptor.errors import ProjectError
from transkryptor.i18n import tr

SCHEMA_VERSION = 6


# Wersja N → N+1. Migracja dostaje słownik w wersji N i zwraca słownik
# w wersji N+1 (z podbitym ``schema_version``); nie zmienia wejścia.
def _add_asr_context(data: dict[str, Any]) -> dict[str, Any]:
    """1 → 2 (wydanie 0.4.0): pusty kontekst nagrania i słownik projektu."""
    return {
        **data,
        "schema_version": 2,
        "asr_context": {"prompt": "", "vocabulary": []},
    }


def _add_ignored_warnings(data: dict[str, Any]) -> dict[str, Any]:
    """2 → 3 (faza 10): brak zignorowanych ostrzeżeń walidatora."""
    return {**data, "schema_version": 3, "ignored_warnings": []}


def _add_anchors(data: dict[str, Any]) -> dict[str, Any]:
    """3 → 4 (faza 11): tekst bez kotwic czasowych."""
    return {**data, "schema_version": 4, "anchors": []}


def _add_speakers(data: dict[str, Any]) -> dict[str, Any]:
    """4 → 5 (faza 12): domyślni mówcy, akapity bez przypisań."""
    document = data.get("document")
    if not isinstance(document, dict):
        return {**data, "schema_version": 5}  # błąd zgłosi parsowanie
    speakers = [
        {"key": s.key, "label": s.label, "role": s.role} for s in DEFAULT_SPEAKERS
    ]
    return {
        **data,
        "schema_version": 5,
        "document": {**document, "speakers": speakers, "paragraph_speakers": []},
    }


def _add_comments(data: dict[str, Any]) -> dict[str, Any]:
    """5 → 6 (faza 14): brak komentarzy recenzji i sprawdzonych zakresów."""
    return {**data, "schema_version": 6, "comments": [], "verified": []}


_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _add_asr_context,
    2: _add_ignored_warnings,
    3: _add_anchors,
    4: _add_speakers,
    5: _add_comments,
}


def migrate(data: Any) -> dict[str, Any]:
    """Podnosi projekt do bieżącej wersji schematu.

    Projekt z nowszej wersji aplikacji jest odrzucany zrozumiałym błędem -
    odczyt mógłby po cichu zgubić nieznane dane.
    """
    if not isinstance(data, dict):
        raise invalid()
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise invalid()
    if version > SCHEMA_VERSION:
        raise ProjectError(
            user_message=tr(
                "project.error.newer", version=version, supported=SCHEMA_VERSION
            ),
            retry_hint=tr("project.error.newer.hint"),
        )
    while version < SCHEMA_VERSION:
        data = _MIGRATIONS[version](data)
        version = data["schema_version"]
    return data
