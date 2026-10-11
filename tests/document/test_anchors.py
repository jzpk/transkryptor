"""Testy modelu kotwic czasowych (faza 11, propozycje 4 i 9)."""

from dataclasses import dataclass

import pytest

from transkryptor.document.anchors import (
    MANUAL,
    SEGMENT,
    WORD,
    Anchor,
    TimeIndex,
    anchor_at,
    build_draft,
    check_anchor,
)
from transkryptor.notation.ellipsis import EllipsisStyle, normalize_ellipses


@dataclass(frozen=True)
class Word:
    start_s: float
    end_s: float
    text: str
    probability: float


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    text: str
    words: tuple[Word, ...] = ()


def texts(draft: str, anchors: list[Anchor], source: str) -> list[str]:
    return [draft[a.start : a.end] for a in anchors if a.source == source]


class TestBuildDraft:
    def test_segments_are_located_after_stripping(self) -> None:
        segments = [
            Segment(0.0, 2.0, " Ala ma kota."),
            Segment(2.0, 3.5, " A kot ma Alę."),
        ]
        text = "".join(s.text for s in segments).strip()
        draft, anchors = build_draft(text, segments)
        assert draft == "Ala ma kota. A kot ma Alę."
        assert texts(draft, anchors, SEGMENT) == ["Ala ma kota.", "A kot ma Alę."]
        assert [(a.start_ms, a.end_ms) for a in anchors] == [(0, 2000), (2000, 3500)]

    def test_ellipsis_normalization_keeps_offsets(self) -> None:
        segments = [
            Segment(0.0, 1.0, " jeż... kam...", (Word(0.0, 0.5, " jeż...", 0.9),)),
            Segment(1.0, 2.0, " są.", (Word(1.0, 2.0, " są.", 0.2),)),
        ]
        text = "".join(s.text for s in segments).strip()
        draft, anchors = build_draft(
            text,
            segments,
            lambda value: normalize_ellipses(value, EllipsisStyle.UNICODE),
        )
        assert draft == "jeż… kam… są."
        assert texts(draft, anchors, SEGMENT) == ["jeż… kam…", "są."]
        assert texts(draft, anchors, WORD) == ["jeż…", "są."]
        word = [a for a in anchors if a.source == WORD][1]
        assert word.probability == 0.2

    def test_missing_fragment_has_no_anchor(self) -> None:
        segments = [
            Segment(0.0, 1.0, " raz", (Word(0.0, 1.0, " nieznane", 0.1),)),
            Segment(1.0, 2.0, " zupełnie inne"),
            Segment(2.0, 3.0, " dwa"),
        ]
        draft, anchors = build_draft("raz dwa", segments)
        assert texts(draft, anchors, SEGMENT) == ["raz", "dwa"]
        assert texts(draft, anchors, WORD) == []

    def test_repeated_words_are_located_in_order(self) -> None:
        words = tuple(
            Word(i * 0.5, i * 0.5 + 0.5, f" {w}", 0.5)
            for i, w in enumerate(["no", "no", "tak"])
        )
        segments = [Segment(0.0, 1.5, " no no tak", words)]
        draft, anchors = build_draft("no no tak", segments)
        assert [(a.start, a.end) for a in anchors if a.source == WORD] == [
            (0, 2),
            (3, 5),
            (6, 9),
        ]


class TestAnchorAt:
    ANCHORS = [
        Anchor(0, 10, 0, 1000, SEGMENT),
        Anchor(0, 3, 0, 300, WORD, probability=0.9),
        Anchor(11, 20, 1000, 2000, SEGMENT),
        Anchor(15, 15, 1500, 1500, MANUAL),
    ]

    def test_word_is_preferred(self) -> None:
        assert anchor_at(self.ANCHORS, 2) == self.ANCHORS[1]
        assert anchor_at(self.ANCHORS, 2, word_level=False) == self.ANCHORS[0]

    def test_containing_or_preceding_anchor(self) -> None:
        assert anchor_at(self.ANCHORS, 12) == self.ANCHORS[2]
        assert anchor_at(self.ANCHORS, 16) == self.ANCHORS[3]
        assert anchor_at(self.ANCHORS, 15) == self.ANCHORS[3]
        assert anchor_at(self.ANCHORS, 40) == self.ANCHORS[3]

    def test_no_anchor_before_position(self) -> None:
        assert anchor_at([Anchor(5, 9, 0, 1, SEGMENT)], 2) is None


def test_time_index_finds_active_segment() -> None:
    anchors = [
        Anchor(10, 20, 2000, 3000, SEGMENT),
        Anchor(0, 5, 0, 1000, SEGMENT),
        Anchor(0, 2, 0, 500, WORD, probability=0.5),
    ]
    index = TimeIndex(anchors)
    assert index.active_at(500) == 1
    assert index.active_at(1500) is None
    assert index.active_at(2999) == 0
    assert index.active_at(3000) is None
    assert TimeIndex([]).active_at(10) is None


def test_uncertain_word() -> None:
    word = Anchor(0, 3, 0, 300, WORD, probability=0.3)
    assert word.is_uncertain(0.4)
    assert not word.is_uncertain(0.3)
    assert not Anchor(0, 3, 0, 300, WORD, 0.3, edited=True).is_uncertain(0.4)
    assert not Anchor(0, 3, 0, 300, SEGMENT).is_uncertain(0.4)


@pytest.mark.parametrize(
    "anchor",
    [
        Anchor(0, 5, 0, 1, SEGMENT),
        Anchor(2, 1, 0, 1, SEGMENT),
        Anchor(0, 1, 0, 1, "inne"),
        Anchor(0, 1, 0, 1, MANUAL),
        Anchor(1, 1, 0, 1, WORD),
        Anchor(0, 1, 2, 1, SEGMENT),
    ],
)
def test_check_anchor_rejects(anchor: Anchor) -> None:
    with pytest.raises(ValueError):
        check_anchor(anchor, 4)
