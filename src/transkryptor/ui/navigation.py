"""Przejście do następnego albo poprzedniego miejsca w tekście (bez Qt).

Wspólna reguła skrótów „następne/poprzednie niepewne słowo” i „następny/
poprzedni komentarz” - jak F3 w wyszukiwaniu: od kursora (za zaznaczeniem)
w przód albo przed kursor w tył, z zawinięciem na drugi koniec tekstu.
"""

from __future__ import annotations

from collections.abc import Sequence

FORWARD = 1
BACKWARD = -1


def step(
    ranges: Sequence[tuple[int, int]],
    selection: tuple[int, int],
    direction: int,
) -> tuple[int, bool] | None:
    """Indeks celu w ``ranges`` (posortowanych po początku) i czy zawinięto.

    ``selection`` to zaznaczenie kursora (``start == end`` - sam kursor).
    W przód: pierwszy zakres zaczynający się od końca zaznaczenia, inny niż
    zaznaczony; w tył: ostatni zaczynający się przed zaznaczeniem. None -
    brak zakresów.
    """
    if not ranges:
        return None
    start, end = selection
    if direction >= FORWARD:
        for index, candidate in enumerate(ranges):
            if candidate[0] >= end and candidate != selection:
                return index, False
        return 0, True
    for index in range(len(ranges) - 1, -1, -1):
        if ranges[index][0] < start:
            return index, False
    return len(ranges) - 1, True
