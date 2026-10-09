"""Wyszukiwanie w tekście transkrypcji i składnia zamiennika z indeksem górnym.

Czyste funkcje bez Qt (propozycja 20): kompilacja zapytania z opcjami,
lista trafień oraz parsowanie zamiennika, w którym ``^x`` oznacza znak ``x``
w indeksie górnym (np. ``be^ndzie``), a ``\\^`` — dosłowny ``^``.

Zamiennik jest zawsze dosłowny, także w trybie wyrażeń regularnych (bez
odwołań do grup ``\\1``).

Wyszukiwanie działa w wątku UI, a krótki wzorzec z katastrofalnym nawrotem
(np. ``(a|aa)+$``) potrafi liczyć się w nieskończoność (SEC-03). Dlatego
wzorce kompiluje pakiet ``regex`` (składnia zgodna z ``re``), a
:func:`find_all` ma łączny limit czasu ``SEARCH_TIMEOUT_S`` — po nim
zgłasza ``SearchError`` z prośbą o prostszy wzorzec. Limity długości wzorca
i liczby trafień ograniczają koszt reszty interfejsu.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import regex

from transkryptor.i18n import tr

MAX_PATTERN_LENGTH = 200
MAX_MATCHES = 10_000
SEARCH_TIMEOUT_S = 0.3


class SearchError(ValueError):
    """Błędne zapytanie lub zamiennik — komunikat dla użytkownika."""


@dataclass(frozen=True)
class SearchOptions:
    case_sensitive: bool = False
    whole_words: bool = False
    regex: bool = False


@dataclass(frozen=True)
class ParsedReplacement:
    """Tekst zamiennika i zakresy indeksu górnego względem jego początku."""

    text: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()


def compile_query(query: str, options: SearchOptions) -> regex.Pattern[str]:
    """Kompiluje zapytanie; rzuca ``SearchError`` z czytelnym komunikatem."""
    if len(query) > MAX_PATTERN_LENGTH:
        raise SearchError(tr("search.error.too_long", limit=MAX_PATTERN_LENGTH))
    pattern = query if options.regex else regex.escape(query)
    if options.whole_words:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    flags = 0 if options.case_sensitive else regex.IGNORECASE
    try:
        return regex.compile(pattern, flags)
    except regex.error as error:
        # ``msg`` (bez pozycji) istnieje w regex.error, choć nie w stubach.
        reason = getattr(error, "msg", None) or str(error)
        raise SearchError(tr("search.error.regex", reason=reason)) from error


def find_all(
    text: str, pattern: regex.Pattern[str], timeout_s: float = SEARCH_TIMEOUT_S
) -> list[tuple[int, int]]:
    """Niepuste trafienia jako zakresy ``(start, end)``, najwyżej ``MAX_MATCHES``.

    Całe wyszukiwanie mieści się w ``timeout_s``; po przekroczeniu —
    ``SearchError`` („wzorzec zbyt kosztowny”). ``timeout`` pakietu
    ``regex`` dotyczy jednego dopasowania, więc kolejne wyszukiwania
    dostają resztę wspólnego terminu.
    """
    deadline = time.monotonic() + timeout_s
    matches: list[tuple[int, int]] = []
    position = 0
    while position <= len(text) and len(matches) < MAX_MATCHES:
        remaining = deadline - time.monotonic()
        try:
            if remaining <= 0:
                raise TimeoutError
            match = pattern.search(text, position, timeout=remaining)
        except TimeoutError as error:
            raise SearchError(
                tr("search.error.too_slow", limit=f"{timeout_s:g}")
            ) from error
        if match is None:
            break
        start, end = match.span()
        if start == end:
            position = end + 1  # puste dopasowania pomijamy
            continue
        matches.append((start, end))
        position = end
    return matches


def parse_replacement(template: str) -> ParsedReplacement:
    """Rozbiera zamiennik: ``^x`` → ``x`` w indeksie górnym, ``\\^`` → ``^``.

    Sąsiednie znaki w indeksie górnym (``^n^d``) tworzą jeden zakres.
    """
    chars: list[str] = []
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < len(template):
        char = template[i]
        if char == "\\" and template.startswith("^", i + 1):
            chars.append("^")
            i += 2
            continue
        if char == "^":
            if i + 1 >= len(template):
                raise SearchError(tr("search.error.caret"))
            position = len(chars)
            chars.append(template[i + 1])
            if ranges and ranges[-1][1] == position:
                ranges[-1] = (ranges[-1][0], position + 1)
            else:
                ranges.append((position, position + 1))
            i += 2
            continue
        chars.append(char)
        i += 1
    return ParsedReplacement("".join(chars), tuple(ranges))
