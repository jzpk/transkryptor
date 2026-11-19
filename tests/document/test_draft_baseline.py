"""Szkic odniesienia wniosków z poprawek (zgłoszenie #74)."""

from transkryptor.document.diff import Version
from transkryptor.document.draft_baseline import absorb


def test_absorb_takes_only_changes_in_the_range() -> None:
    baseline = Version("ala ma kota\ni psa", (), {1: "I"})
    current = Version("ala ma kotka\nwstawka i psa", (), {1: "I"})
    start = current.text.index("wstawka")
    absorbed = absorb(baseline, current, start, start + len("wstawka "))
    # Wstawka należy do szkicu, a poprawka „kota → kotka” zostaje poprawką.
    assert absorbed.text == "ala ma kota\nwstawka i psa"
    assert absorbed.paragraph_speakers == {1: "I"}


def test_absorb_keeps_superscript_of_the_fragment() -> None:
    baseline = Version("bendzie")
    current = Version("bendzie", ((2, 3),))
    assert absorb(baseline, current, 0, 7).superscript_ranges == ((2, 3),)
