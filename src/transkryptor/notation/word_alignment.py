"""Parowanie słów zamienionego fragmentu szkicu i tekstu (zgłoszenie #74, bez Qt).

W fragmencie, który transkrybent przepisał, słowa szkicu i poprawionego
tekstu trzeba połączyć w pary (poprawka słowa), a słowa bez pary uznać za
wstawki albo usunięcia. :func:`align_words` robi to programowaniem
dynamicznym z podobieństwem napisów jako zyskiem pary, a :func:`rewritten`
odróżnia słowo przepisane w całości (``tylko → ino``) od zmiany zapisu
(``kiedy → kiej``).
"""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher


def rewritten(original: str, corrected: str) -> bool:
    """Słowo przepisane w całości: wspólny początek i koniec to mniej niż
    połowa słowa (``tylko → ino``), a nie zmiana zapisu (``kiedy → kiej``)."""
    a, b = original.casefold(), corrected.casefold()
    prefix = 0
    while prefix < min(len(a), len(b)) and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(a), len(b)) - prefix and a[-1 - suffix] == b[-1 - suffix]:
        suffix += 1
    return 2 * (prefix + suffix) < len(a)


# Para słów jest poprawką, gdy są choć trochę podobne; inaczej to wstawka
# i usunięcie. Dłuższe zamiany nie są dopasowywane słowo do słowa.
PAIR_SIMILARITY = 0.34
MAX_ALIGNED = 60


def align_words(
    old: Sequence[str], new: Sequence[str]
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Pary podobnych słów (kolejność zachowana) i słowa bez pary po obu stronach.

    Programowanie dynamiczne z podobieństwem napisów jako zyskiem pary - tak
    „Kiedy będzie” → „kiej nie beⁿdzie” daje dwie pary i wstawkę „nie”.
    """
    if len(old) == len(new) and len(old) <= MAX_ALIGNED:
        return list(zip(range(len(old)), range(len(new)), strict=True)), [], []
    if len(old) > MAX_ALIGNED or len(new) > MAX_ALIGNED:
        return [], list(range(len(old))), list(range(len(new)))
    rows, cols = len(old), len(new)
    score = [[0.0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            gain = _similarity(old[i], new[j])
            paired = score[i + 1][j + 1] + gain if gain >= PAIR_SIMILARITY else -1.0
            score[i][j] = max(paired, score[i + 1][j], score[i][j + 1])
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < rows and j < cols:
        gain = _similarity(old[i], new[j])
        if gain >= PAIR_SIMILARITY and score[i][j] == score[i + 1][j + 1] + gain:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif score[i][j] == score[i + 1][j]:
            i += 1
        else:
            j += 1
    paired_old = {i for i, _ in pairs}
    paired_new = {j for _, j in pairs}
    return (
        pairs,
        [i for i in range(rows) if i not in paired_old],
        [j for j in range(cols) if j not in paired_new],
    )


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def runs(indices: Sequence[int]) -> list[list[int]]:
    """Kolejne numery zgrupowane w ciągi (sąsiednie słowa to jedna wstawka)."""
    runs: list[list[int]] = []
    for index in indices:
        if runs and runs[-1][-1] == index - 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


__all__ = ["align_words", "rewritten", "runs"]
