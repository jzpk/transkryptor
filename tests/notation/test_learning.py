"""Reguły fonetyczne z poprawek: wykrywanie powtarzalnych zmian (bez Qt)."""

import pytest

from transkryptor.notation.learning import (
    FINAL,
    INITIAL,
    INNER,
    Change,
    Correction,
    candidates,
    change_of,
)
from transkryptor.notation.rules import PhoneticRule
from transkryptor.notation.suggestions import propose_with_report


@pytest.mark.parametrize(
    ("correction", "expected"),
    [
        # „ę” → „eⁿ”: indeks górny w zamienniku.
        (Correction("będzie", "bendzie", ((2, 3),)), Change("ę", "e^n", INNER)),
        (Correction("są", "som", ((2, 3),)), Change("ą", "o^m", FINAL)),
        (Correction("jak", "jag"), Change("k", "g", FINAL)),
        # Samo wstawienie obejmuje sąsiedni znak („ł” protetyczne).
        (Correction("ojciec", "łojciec"), Change("o", "ło", INITIAL)),
        (Correction("pamiętam", "pamientam"), Change("ę", "en", INNER)),
        # Samo usunięcie obejmuje poprzednią literę.
        (Correction("dzień", "dziń"), Change("ie", "i", INNER)),
        # Wstawiony indeks górny dokleja się do poprzedniej litery.
        (Correction("mleko", "mlenko", ((3, 4),)), Change("e", "e^n", INNER)),
    ],
)
def test_change_of_correction(correction: Correction, expected: Change) -> None:
    assert change_of(correction) == expected


@pytest.mark.parametrize(
    "correction",
    [
        Correction("tak", "tak"),
        Correction("Tak", "tak"),  # wielkość liter to nie zapis fonetyczny
        Correction("dom", "las"),  # przepisane całe słowo
        Correction("przyjechali", "przyszli"),  # zmiana za długa
    ],
)
def test_corrections_that_are_not_patterns(correction: Correction) -> None:
    assert change_of(correction) is None


def nasal(word: str, corrected: str, index: int) -> Correction:
    return Correction(word, corrected, ((index, index + 1),))


def test_repeated_change_becomes_a_rule_with_context() -> None:
    corrections = [
        nasal("będzie", "bendzie", 2),
        nasal("pędzi", "pendzi", 2),
        nasal("mądry", "mondry", 2),  # inna zmiana - raz
        nasal("będą", "bendą", 2),
    ]
    (candidate,) = candidates(corrections)
    assert candidate.count == 3
    assert candidate.example == "będzie"
    rule = candidate.rule
    assert rule.code == "USR-1"
    assert rule.replacement == "e^n"
    # Wszystkie poprawki mają „d” za zmianą: wzorzec to uwzględnia.
    assert rule.pattern == "(?<=[bp])ę(?=d)"
    (suggestion,) = propose_with_report("będziemy", [rule]).suggestions
    assert suggestion.replacement == "en"
    assert suggestion.superscript_ranges == ((1, 2),)
    assert propose_with_report("więcej", [rule]).suggestions == []


def test_final_change_and_varied_context() -> None:
    corrections = [Correction(w, w[:-1] + "g") for w in ("jak", "bok", "puk", "lek")]
    (candidate,) = candidates(corrections)
    assert candidate.count == 4
    # Cztery różne znaki przed zmianą - bez warunku kontekstu.
    assert candidate.rule.pattern == "k$"


def test_below_threshold_dismissed_and_existing_are_skipped() -> None:
    corrections = [Correction(w, w[:-1] + "g") for w in ("jak", "tak", "pak")]
    assert candidates(corrections[:2]) == []
    (candidate,) = candidates(corrections)
    assert candidates(corrections, dismissed=[candidate.change.key]) == []
    existing = PhoneticRule(
        code="USR-1",
        label={"*": "k → g"},
        pattern=candidate.rule.pattern,
        replacement="g",
        confidence=0.5,
    )
    assert candidates(corrections, existing=[existing]) == []
    other = PhoneticRule(
        code="USR-1", label={"*": "x"}, pattern="x", replacement="y", confidence=0.5
    )
    (fresh,) = candidates(corrections, existing=[other])
    assert fresh.rule.code == "USR-2"
