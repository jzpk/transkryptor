"""Zapis szkicu ASR: skróty w pełnym brzmieniu (zgłoszenie #42)."""

import pytest

from transkryptor.asr.draft_style import DraftStyle, apply_style, expand_text
from transkryptor.asr.engine import SegmentResult, TranscriptionResult, WordResult
from transkryptor.document.inflection import morfeusz_inflector


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
