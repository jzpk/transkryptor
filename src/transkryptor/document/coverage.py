"""Mapa pokrycia transkrypcji: luki nagrania bez tekstu (bez Qt).

Pokrycie nagrania tekstem liczy ``document/progress.py`` (kotwice szkicu
ASR i ręczne znaczniki czasu) - ta sama definicja trafia do okna
„Statystyki projektu” i na falę dźwiękową. Luka to fragment nagrania bez
tekstu, dłuższy niż ``MIN_GAP_MS`` (krótsze to zwykłe pauzy). Cisza
wykryta w obwiedni nagrania (``audio/envelope.py``) nie jest luką - nie ma
w niej czego transkrybować.
"""

from __future__ import annotations

from collections.abc import Iterable

from transkryptor.document.verification import clipped, normalized, remove

Range = tuple[int, int]

# Krótsza luka w tekście to zwykła pauza, nie pominięty fragment.
MIN_GAP_MS = 3000


def uncovered(covered: Iterable[Range], duration_ms: int) -> tuple[Range, ...]:
    """Fragmenty nagrania ``[0, duration_ms)`` bez tekstu."""
    result: list[Range] = []
    cursor = 0
    for start, end in clipped(covered, duration_ms):
        if start > cursor:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if duration_ms > cursor:
        result.append((cursor, duration_ms))
    return tuple(result)


def transcription_gaps(
    covered: Iterable[Range],
    duration_ms: int,
    silence: Iterable[Range] = (),
    min_gap_ms: int = MIN_GAP_MS,
) -> tuple[Range, ...]:
    """Luki w transkrypcji: bez tekstu, bez ciszy, nie krótsze niż próg."""
    holes = uncovered(covered, duration_ms)
    for start, end in normalized(silence):
        holes = remove(holes, start, end)
    return tuple((a, b) for a, b in holes if b - a >= min_gap_ms)


def gap_target(
    gaps: Iterable[Range], position_ms: int, forward: bool = True
) -> tuple[int, bool] | None:
    """Początek następnej (albo poprzedniej) luki i czy wyszukiwanie zawinęło.

    „Następna” to pierwsza luka zaczynająca się za pozycją, „poprzednia” -
    ostatnia zaczynająca się przed nią (z marginesem pół sekundy, żeby
    powtórne naciśnięcie nie stało w miejscu). None - brak luk.
    """
    starts = sorted(start for start, _end in gaps)
    if not starts:
        return None
    if forward:
        later = [start for start in starts if start > position_ms]
        return (later[0], False) if later else (starts[0], True)
    earlier = [start for start in starts if start < position_ms - 500]
    return (earlier[-1], False) if earlier else (starts[-1], True)
