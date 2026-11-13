"""Układ szkicu „pytanie - odpowiedź” według znaków zapytania (zgłoszenie #41)."""

from transkryptor.asr.engine import (
    SegmentResult,
    TranscriptionResult,
    WordResult,
    draft_line_speakers,
    draft_text,
)
from transkryptor.asr.qa_layout import (
    ANSWER,
    QUESTION,
    ends_with_question,
    question_answer_layout,
)


def result(*segments: SegmentResult) -> TranscriptionResult:
    text = "".join(segment.text for segment in segments).strip()
    return TranscriptionResult(text=text, language="pl", segments=segments)


def test_questions_and_answers_get_their_own_lines() -> None:
    draft = result(
        SegmentResult(0.0, 4.0, " Imię i nazwisko? Krystyna Adamek.", 0.9),
        SegmentResult(4.0, 9.0, " Rok i miejsce urodzenia? 1954. W Maniewie.", 0.9),
    )
    layout = question_answer_layout(draft)
    assert [s.speaker for s in layout.segments] == [
        QUESTION,
        ANSWER,
        QUESTION,
        ANSWER,
        ANSWER,
    ]
    assert draft_text(layout) == (
        "[00:00] Imię i nazwisko?\n"
        "[00:02] Krystyna Adamek.\n"
        "[00:04] Rok i miejsce urodzenia?\n"
        "[00:06] 1954. W Maniewie."
    )
    assert draft_line_speakers(layout) == [QUESTION, ANSWER, QUESTION, ANSWER]


def test_sentence_times_come_from_words_across_segments() -> None:
    words_a = (
        WordResult(0.0, 0.5, " Gdzie", 0.9),
        WordResult(0.5, 1.0, " pani", 0.9),
    )
    words_b = (
        WordResult(2.0, 2.5, " mieszka?", 0.9),
        WordResult(3.0, 3.5, " Tu.", 0.9),
    )
    draft = result(
        SegmentResult(0.0, 1.0, " Gdzie pani", 0.8, words_a),
        SegmentResult(2.0, 3.5, " mieszka? Tu.", 0.6, words_b),
    )
    question, answer = question_answer_layout(draft).segments
    assert (question.start_s, question.end_s) == (0.0, 2.5)
    assert question.text == " Gdzie pani mieszka?"
    assert question.confidence == 0.6
    assert [w.text for w in question.words] == [" Gdzie", " pani", " mieszka?"]
    assert (answer.start_s, answer.text, answer.speaker) == (3.0, " Tu.", ANSWER)


def test_custom_question_detection() -> None:
    draft = result(SegmentResult(0.0, 2.0, " Miejscowość. Ocieszyn.", 0.9))
    layout = question_answer_layout(
        draft, lambda sentence: sentence.startswith("Miejscowość")
    )
    assert [s.speaker for s in layout.segments] == [QUESTION, ANSWER]


def test_question_mark_detection() -> None:
    assert ends_with_question("Gdzie pani mieszka?")
    assert ends_with_question("A czemu?”")
    assert not ends_with_question("Tu, we wsi.")


def test_empty_result_is_unchanged() -> None:
    draft = TranscriptionResult(text="", language="pl")
    assert question_answer_layout(draft) is draft


def test_phatic_nie_is_an_answer() -> None:
    """Zgłoszenie #45: fatyczne „nie?” nie robi z odpowiedzi pytania."""
    draft = result(
        SegmentResult(0.0, 3.0, " Jak długo tu Pani mieszka? Od urodzenia, nie?", 0.9)
    )
    layout = question_answer_layout(draft)
    assert [s.speaker for s in layout.segments] == [QUESTION, ANSWER]
