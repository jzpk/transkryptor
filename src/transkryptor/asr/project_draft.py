"""Szkic ASR w projekcie: wynik transkrypcji ↔ ``AsrDraft`` pliku ``.transkr``.

Projekt zapisuje własne klasy szkicu (``document/project``), a panel ASR
pracuje na wyniku silnika (``asr/results.py``) - tu jest jedyna konwersja
w obie strony, bez Qt.
"""

from __future__ import annotations

from transkryptor.asr.results import SegmentResult, TranscriptionResult, WordResult
from transkryptor.document.project import AsrDraft, AsrSegment, AsrWord


def draft_from_result(result: TranscriptionResult, model: str | None) -> AsrDraft:
    """Szkic do zapisu w projekcie (``model`` - klucz modelu transkrypcji)."""
    return AsrDraft(
        text=result.text,
        language=result.language,
        segments=tuple(
            AsrSegment(
                s.start_s,
                s.end_s,
                s.text,
                s.confidence,
                tuple(
                    AsrWord(w.start_s, w.end_s, w.text, w.probability) for w in s.words
                ),
                speaker=s.speaker,
            )
            for s in result.segments
        ),
        model=model,
    )


def result_from_draft(draft: AsrDraft | None) -> TranscriptionResult | None:
    """Wynik dla panelu ASR ze szkicu z projektu (None - projekt bez szkicu)."""
    if draft is None:
        return None
    return TranscriptionResult(
        text=draft.text,
        language=draft.language,
        segments=tuple(
            SegmentResult(
                s.start_s,
                s.end_s,
                s.text,
                s.confidence,
                tuple(
                    WordResult(w.start_s, w.end_s, w.text, w.probability)
                    for w in s.words
                ),
                speaker=s.speaker,
            )
            for s in draft.segments
        ),
    )


__all__ = ["draft_from_result", "result_from_draft"]
