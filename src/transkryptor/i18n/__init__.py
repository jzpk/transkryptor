"""Teksty interfejsu w wielu językach (bez zależności od Qt).

Katalogi tłumaczeń to pliki ``locales/<kod>.json``: płaskie słowniki
klucz → tekst z polami ``str.format`` (``{name}``). Język jest wybierany raz,
przy starcie (``set_language``); zmiana w ustawieniach działa po ponownym
uruchomieniu. Dodanie języka to nowy plik JSON i wpis w ``LANGUAGES``.

Teksty pobiera się wywołaniem ``tr(klucz)`` w chwili użycia — nigdy w stałej
modułowej, bo ta zamroziłaby język z chwili importu.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

POLISH = "pl"
ENGLISH = "en"
# Nazwy języków w nich samych — tak pokazuje je lista wyboru w ustawieniach.
LANGUAGES = {POLISH: "Polski", ENGLISH: "English"}
# Katalog zapasowy dla kluczy brakujących w bieżącym języku.
FALLBACK_LANGUAGE = POLISH
# Język, gdy system nie wskazuje żadnego z obsługiwanych.
DEFAULT_FOREIGN_LANGUAGE = ENGLISH

_current = FALLBACK_LANGUAGE


@cache
def catalog(language: str) -> dict[str, str]:
    """Katalog tłumaczeń języka; pusty, gdy pliku nie ma lub jest uszkodzony."""
    try:
        raw = (
            resources.files(__package__)
            .joinpath("locales", f"{language}.json")
            .read_text(encoding="utf-8")
        )
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, str)}


def set_language(language: str) -> str:
    """Ustawia język tekstów; nieznany kod oznacza język zapasowy."""
    global _current
    _current = language if language in LANGUAGES else FALLBACK_LANGUAGE
    return _current


def current_language() -> str:
    return _current


def resolve_language(setting: str, system_locale_name: str) -> str:
    """Kod języka z ustawienia; ``system`` → język systemu (np. ``pl_PL``)."""
    if setting in LANGUAGES:
        return setting
    code = system_locale_name.replace("-", "_").split("_")[0].lower()
    return code if code in LANGUAGES else DEFAULT_FOREIGN_LANGUAGE


def tr(key: str, **kwargs: object) -> str:
    """Tekst w bieżącym języku; brak tłumaczenia → język zapasowy → klucz.

    Nigdy nie rzuca wyjątku: błędne pola formatu zostawiają tekst bez zmian.
    """
    text = catalog(_current).get(key)
    if text is None:
        text = catalog(FALLBACK_LANGUAGE).get(key, key)
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text


def plural_form(language: str, count: int) -> str:
    """Forma liczby mnogiej: ``one``, ``few`` (tylko polski: 2–4) albo ``many``."""
    if count == 1:
        return "one"
    if (
        language == POLISH
        and count % 10 in (2, 3, 4)
        and count % 100 not in (12, 13, 14)
    ):
        return "few"
    return "many"


def tr_plural(key: str, count: int, **kwargs: object) -> str:
    """Tekst odmieniony przez liczbę: klucze ``<key>.one``, ``.few``, ``.many``.

    Pole ``{count}`` jest dostępne w tekście. Każdy język ma wszystkie trzy
    klucze (w angielskim ``few`` = ``many``).
    """
    form = plural_form(_current, count)
    return tr(f"{key}.{form}", count=count, **kwargs)


def all_translations(key: str) -> tuple[str, ...]:
    """Tekst klucza we wszystkich językach (np. do rozpoznania etykiet DOCX)."""
    texts: list[str] = []
    for language in LANGUAGES:
        text = catalog(language).get(key)
        if text is not None and text not in texts:
            texts.append(text)
    return tuple(texts)


__all__ = [
    "ENGLISH",
    "LANGUAGES",
    "POLISH",
    "all_translations",
    "catalog",
    "current_language",
    "resolve_language",
    "set_language",
    "plural_form",
    "tr",
    "tr_plural",
]
