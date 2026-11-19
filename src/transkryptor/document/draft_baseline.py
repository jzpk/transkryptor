"""Szkic ASR po wstawieniu - wersja odniesienia wniosków z poprawek (#74, bez Qt).

Wnioski z poprawek porównują tekst z edytora ze szkiciem w chwili wstawienia
(po regułach wybranych przy wstawianiu). Zmiany, które nie są poprawkami
transkrybenta - fragment dopisany transkrypcją A-B albo propozycja reguły
przyjęta później w przeglądzie - trzeba „wchłonąć” do szkicu odniesienia, żeby
nie wyglądały na poprawki. :func:`absorb` przenosi do niego zmiany bieżącej
wersji leżące w podanym zakresie.
"""

from __future__ import annotations

from transkryptor.document.diff import SPEAKER, Version, apply_change, diff_versions


def absorb(baseline: Version, current: Version, start: int, end: int) -> Version:
    """Szkic odniesienia ze zmianami ``current`` z zakresu ``[start, end)``.

    Pozycje są w wersji bieżącej. Zmiana trafia do szkicu, gdy w wersji
    bieżącej nachodzi na zakres (wstawienie - gdy leży w nim albo na jego
    brzegu); pozostałe zmiany zostają poprawkami.
    """
    chosen = [
        change
        for change in diff_versions(baseline, current)
        if change.kind != SPEAKER
        and (
            change.b_start < end
            and change.b_end > start
            or start <= change.b_start <= change.b_end <= end
        )
    ]
    for change in sorted(chosen, key=lambda c: c.a_start, reverse=True):
        baseline = apply_change(baseline, current, change)
    return baseline


__all__ = ["absorb"]
