"""Szkic ASR w projekcie: wynik silnika ↔ AsrDraft (bez Qt)."""

from transkryptor.asr.project_draft import draft_from_result, result_from_draft
from transkryptor.asr.results import SegmentResult, TranscriptionResult, WordResult


def test_draft_round_trip_keeps_words_and_speakers() -> None:
    result = TranscriptionResult(
        text="Dom. Tu.",
        language="pl",
        segments=(
            SegmentResult(
                0.0, 1.0, " Dom.", 0.9, (WordResult(0.0, 1.0, " Dom.", 0.8),), 0
            ),
            SegmentResult(1.0, 2.0, " Tu.", 0.7, speaker=1),
        ),
    )
    draft = draft_from_result(result, "medium")
    assert draft.model == "medium"
    assert result_from_draft(draft) == result
    assert result_from_draft(None) is None
