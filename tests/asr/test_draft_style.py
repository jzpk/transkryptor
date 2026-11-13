"""Zapis szkicu ASR: skróty (zgłoszenie #42) i zapis mowy (zgłoszenie #37)."""

import pytest

from transkryptor.asr.abbreviations import expand_text
from transkryptor.asr.draft_style import DraftStyle, apply_style, style_text
from transkryptor.asr.engine import SegmentResult, TranscriptionResult, WordResult
from transkryptor.document.inflection import morfeusz_inflector
from transkryptor.document.proper_names import morfeusz_proper_names


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" np. taka przepowiednia", " na przykład taka przepowiednia"),
        (" Np. Kasia ma myszkę", " Na przykład Kasia ma myszkę"),
        (" m.in. wesele", " między innymi wesele"),
        (" sznurki, nici itp.", " sznurki, nici i tym podobne."),
        (" i tak było itd. Potem", " i tak było i tak dalej. Potem"),
        (" to jest, tzn. dom", " to jest, to znaczy dom"),
        (" wg mnie", " według mnie"),
        (" ok. 20 lat", " około 20 lat"),
        (" No dobra, ok.", " No dobra, ok."),
        (" tzw. dom", " tak zwany dom"),
    ],
)
def test_abbreviations_are_spelled_out(text, expected) -> None:
    assert expand_text(text) == expected


def test_so_called_agrees_with_the_next_word() -> None:
    inflector = morfeusz_inflector()

    def agree(word: str) -> str | None:
        return inflector.agreeing("zwać", word)

    assert expand_text(" ma tzw. myszkę", agree) == " ma tak zwaną myszkę"
    assert expand_text(" tzw. domu", agree) == " tak zwanego domu"
    assert expand_text(" tzw. dzieci", agree) == " tak zwane dzieci"


def test_result_segments_and_words_are_expanded() -> None:
    words = (
        WordResult(0.0, 0.4, " np.", 0.9),
        WordResult(0.4, 0.9, " kot", 0.9),
    )
    segment = SegmentResult(0.0, 0.9, " np. kot", 0.9, words)
    result = TranscriptionResult(text="np. kot", language="pl", segments=(segment,))

    styled = apply_style(result, DraftStyle())
    assert styled.text == "na przykład kot"
    assert styled.segments[0].text == " na przykład kot"
    assert [w.text for w in styled.segments[0].words] == [" na przykład", " kot"]
    assert apply_style(result, DraftStyle(expand_abbreviations=False)) is result


PLAIN = DraftStyle(expand_abbreviations=False, lowercase_plain=True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" Ala ma kota, a kot ma Alę.", " ala ma kota a kot ma Alę"),
        (" Co to? Nie wiem... Ojej!", " co to? nie wiem... ojej!"),
        (" Było 1.5 roku; tak: krótko.", " było 1.5 roku tak krótko"),
        (" W PRL-u. PRL był", " w PRL-u PRL był"),
        (" „Tak” - mówi.", " „tak” - mówi"),
    ],
)
def test_plain_style_lowercases_sentence_starts_and_drops_stops(text, expected) -> None:
    assert style_text(text, PLAIN) == expected


def test_proper_names_keep_their_capital() -> None:
    names = morfeusz_proper_names()
    style = replace_style(may_be_proper=names.may_be_proper)
    text = " Poznań. Rolnik. Rok i miejsce. Kasia też. Ocieszyn."
    assert style_text(text, style) == " Poznań rolnik rok i miejsce Kasia też Ocieszyn"


def test_sentence_start_carries_over_segments_and_words() -> None:
    first_words = (WordResult(0.0, 1.0, " Dom.", 0.9),)
    second_words = (
        WordResult(1.0, 1.5, " Tu", 0.9),
        WordResult(1.5, 2.0, " mieszkam.", 0.9),
    )
    segments = (
        SegmentResult(0.0, 1.0, " Dom.", 0.9, first_words),
        SegmentResult(1.0, 2.0, " Tu mieszkam.", 0.9, second_words),
    )
    result = TranscriptionResult(
        text="Dom. Tu mieszkam.", language="pl", segments=segments
    )
    styled = apply_style(result, PLAIN)
    assert styled.text == "dom tu mieszkam"
    assert [w.text for s in styled.segments for w in s.words] == [
        " dom",
        " tu",
        " mieszkam",
    ]


def replace_style(**changes) -> DraftStyle:
    from dataclasses import replace

    return replace(PLAIN, **changes)
