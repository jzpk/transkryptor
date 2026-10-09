"""Wyszukiwanie w tekście transkrypcji i składnia zamiennika z indeksem górnym.

Czyste funkcje bez Qt (propozycja 20): kompilacja zapytania z opcjami,
lista trafień oraz parsowanie zamiennika, w którym ``^x`` oznacza znak ``x``
w indeksie górnym (np. ``be^ndzie``), a ``\\^`` — dosłowny ``^``.

Zamiennik jest zawsze dosłowny, także w trybie wyrażeń regularnych (bez
odwołań do grup ``\\1``). Moduł ``re`` nie ma limitu czasu, więc ochroną
przed bardzo wolnymi wzorcami jest limit długości wzorca i liczby trafień.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from transkryptor.i18n import tr

MAX_PATTERN_LENGTH = 200
MAX_MATCHES = 10_000


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


def compile_query(query: str, options: SearchOptions) -> re.Pattern[str]:
    """Kompiluje zapytanie; rzuca ``SearchError`` z czytelnym komunikatem."""
    if len(query) > MAX_PATTERN_LENGTH:
        raise SearchError(tr("search.error.too_long", limit=MAX_PATTERN_LENGTH))
    pattern = query if options.regex else re.escape(query)
    if options.whole_words:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    flags = 0 if options.case_sensitive else re.IGNORECASE
    try:
        return re.compile(pattern, flags)
    except re.error as error:
        raise SearchError(tr("search.error.regex", reason=error.msg)) from error


def find_all(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Niepuste trafienia jako zakresy ``(start, end)``, najwyżej ``MAX_MATCHES``."""
    matches: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        if match.start() == match.end():
            continue
        matches.append(match.span())
        if len(matches) >= MAX_MATCHES:
            break
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
