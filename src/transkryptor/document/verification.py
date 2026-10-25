"""Postęp weryfikacji nagrania: sprawdzone zakresy czasu (bez Qt).

Transkrybent oznacza, które fragmenty nagrania ma już odsłuchane
i sprawdzone z tekstem - zwykle „do bieżącego miejsca”, przy pracy
rozłożonej na wiele dni. Stan to posortowane, rozłączne zakresy
``[start_ms, end_ms)``; sąsiadujące i nachodzące zakresy są scalane.
Moduł liczy pokrycie nagrania i niesprawdzone luki; zakresy są zapisywane
w pliku projektu (``ProjectState.verified``).
"""

from __future__ import annotations

from collections.abc import Iterable

Range = tuple[int, int]

# Luka krótsza niż tyle ms nie jest „niesprawdzonym miejscem” (np. ułamek
# sekundy między oznaczeniem a końcem nagrania).
MIN_GAP_MS = 1000


def normalized(ranges: Iterable[Range]) -> tuple[Range, ...]:
    """Zakresy posortowane, bez pustych, ze scalonymi stykającymi się."""
    merged: list[list[int]] = []
    for start, end in sorted((max(0, a), b) for a, b in ranges if b > max(0, a)):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def add(ranges: Iterable[Range], start: int, end: int) -> tuple[Range, ...]:
    return normalized([*ranges, (start, end)])


def remove(ranges: Iterable[Range], start: int, end: int) -> tuple[Range, ...]:
    """Zakresy bez ``[start, end)`` (fragment znów jest niesprawdzony)."""
    result: list[Range] = []
    for a, b in normalized(ranges):
        if b <= start or a >= end:
            result.append((a, b))
            continue
        if a < start:
            result.append((a, start))
        if b > end:
            result.append((end, b))
    return tuple(result)


def mark_until(ranges: Iterable[Range], position_ms: int) -> tuple[Range, ...]:
    """Oznacza jako sprawdzoną lukę kończącą się w ``position_ms``.

    To „sprawdzone do tego miejsca”: od końca poprzedniego sprawdzonego
    zakresu (albo od początku nagrania) do bieżącej pozycji. Pozycja
    w sprawdzonym zakresie niczego nie zmienia.
    """
    current = normalized(ranges)
    if contains(current, position_ms):
        return current
    start = max((b for _a, b in current if b <= position_ms), default=0)
    return add(current, start, position_ms)


def contains(ranges: Iterable[Range], position_ms: int) -> bool:
    return any(a <= position_ms < b for a, b in ranges)


def overlaps(ranges: Iterable[Range], start: int, end: int) -> bool:
    return any(a < end and b > start for a, b in ranges)


def clipped(ranges: Iterable[Range], duration_ms: int) -> tuple[Range, ...]:
    """Zakresy obcięte do długości nagrania."""
    return normalized((a, min(b, duration_ms)) for a, b in ranges)


def covered_ms(ranges: Iterable[Range], duration_ms: int) -> int:
    return sum(b - a for a, b in clipped(ranges, duration_ms))


def coverage(ranges: Iterable[Range], duration_ms: int) -> float:
    """Sprawdzona część nagrania 0.0-1.0 (0 - nieznana długość)."""
    if duration_ms <= 0:
        return 0.0
    return min(1.0, covered_ms(ranges, duration_ms) / duration_ms)


def gaps(ranges: Iterable[Range], duration_ms: int) -> list[Range]:
    """Niesprawdzone luki nagrania (bez luk krótszych niż ``MIN_GAP_MS``)."""
    result: list[Range] = []
    cursor = 0
    for a, b in clipped(ranges, duration_ms):
        if a - cursor >= MIN_GAP_MS:
            result.append((cursor, a))
        cursor = max(cursor, b)
    if duration_ms - cursor >= MIN_GAP_MS:
        result.append((cursor, duration_ms))
    return result


def next_gap(
    ranges: Iterable[Range], position_ms: int, duration_ms: int
) -> tuple[int, bool] | None:
    """Początek niesprawdzonego miejsca od ``position_ms`` i czy zawinięto.

    Pozycja w luce daje początek tej luki (powrót do miejsca, gdzie
    skończyła się weryfikacja), a w sprawdzonym fragmencie - początek
    następnej luki; za ostatnią luką wyszukiwanie wraca do pierwszej.
    None - całe nagranie jest sprawdzone.
    """
    holes = gaps(ranges, duration_ms)
    if not holes:
        return None
    for start, end in holes:
        if position_ms < end:
            return start, False
    return holes[0][0], True
