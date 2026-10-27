"""Zdarzenia panelu ASR w oknie: szkic, fragment, ustawienia i blokada.

Kontroler wstawia gotowy szkic (z podziałem na mówców) i transkrypcję
fragmentu przez ``ReviewController``, zapamiętuje wybór modelu i liczby
mówców w ustawieniach, przekazuje segmenty wyniku do fali dźwięku i na
czas transkrypcji blokuje okno nakładką z postępem i anulowaniem.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject

from transkryptor.asr.engine import (
    TranscriptionResult,
    draft_line_speakers,
    draft_text,
)
from transkryptor.document.model import Document
from transkryptor.document.speakers import speakers_for_clusters
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.autosave import AutosaveController
from transkryptor.ui.compare_controller import CompareController
from transkryptor.ui.loading_overlay import LoadingOverlay
from transkryptor.ui.review import ReviewController
from transkryptor.ui.settings_store import SettingsStore
from transkryptor.ui.speaker_controller import SpeakerController
from transkryptor.ui.waveform import WaveformController, segment_spans


class AsrController(QObject):
    """Łączy sygnały panelu ASR z dokumentem, ustawieniami i blokadą okna."""

    def __init__(
        self,
        panel: AsrPanel,
        review: ReviewController,
        speakers: SpeakerController,
        compare: CompareController,
        document: Callable[[], Document],
        settings_store: SettingsStore,
        waveform: WaveformController,
        overlay: LoadingOverlay,
        autosave: AutosaveController,
        set_locked: Callable[[bool], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._panel = panel
        self._review = review
        self._speakers = speakers
        self._compare = compare
        self._document = document
        self._settings_store = settings_store
        self._waveform = waveform
        self._overlay = overlay
        self._autosave = autosave
        self._set_locked = set_locked

        panel.draft_ready.connect(self.insert_draft)
        panel.fragment_ready.connect(self.insert_fragment)
        panel.result_changed.connect(self._on_result_changed)
        panel.model_changed.connect(self._on_model_changed)
        panel.speakers_changed.connect(self._on_speakers_changed)
        panel.review_item_activated.connect(review.activate)
        panel.review_item_apply_requested.connect(review.apply)
        panel.review_finish_requested.connect(review.finish)
        panel.transcription_started.connect(self.transcription_started)
        panel.transcription_finished.connect(self.transcription_finished)
        panel.transcription_progress.connect(overlay.set_progress)
        overlay.cancel_requested.connect(panel.cancel_transcription)

    # --- szkic i fragment ----------------------------------------------------

    def insert_draft(self, draft: TranscriptionResult | str) -> None:
        """Wstawia szkic całego nagrania (pytanie o miejsce zadaje przegląd)."""
        self._compare.finish()
        if not isinstance(draft, TranscriptionResult):
            self._review.insert_draft(draft)
            return
        if not draft.diarized:
            self._review.insert_draft(draft_text(draft), draft.segments)
            return
        # Podział na mówców: głosy w kolejności pojawiania się dostają
        # kolejnych mówców z listy (B, I, a brakujący - I2, I3…).
        clusters = draft_line_speakers(draft)
        count = 1 + max(
            (number for number in clusters if number is not None), default=0
        )
        previous = list(self._document().speakers)
        speakers, keys = speakers_for_clusters(previous, count)
        if list(speakers) != previous:
            self._speakers.apply_speakers(list(speakers))
        line_speakers = [
            None if number is None else keys[number] for number in clusters
        ]
        if (
            not self._review.insert_draft(
                draft_text(draft), draft.segments, line_speakers
            )
            and list(speakers) != previous
        ):
            self._speakers.apply_speakers(previous)

    def insert_fragment(self, result: TranscriptionResult) -> None:
        """Transkrypcja fragmentu A-B trafia w miejsce kursora."""
        self._compare.finish()
        self._review.insert_fragment(result.text, result.segments)

    def _on_result_changed(self) -> None:
        result = self._panel.last_result
        self._waveform.set_segments(
            segment_spans(result.segments) if result is not None else []
        )

    # --- ustawienia z panelu -------------------------------------------------

    def _on_model_changed(self, key: str) -> None:
        """Wybór modelu w panelu jest zapamiętywany w ustawieniach (ACC-35)."""
        current = self._settings_store.current
        if current.asr.model_key != key:
            self._settings_store.save(
                replace(current, asr=replace(current.asr, model_key=key))
            )

    def _on_speakers_changed(self, count: int) -> None:
        """Liczba mówców wybrana w panelu ASR jest zapamiętywana w ustawieniach."""
        current = self._settings_store.current
        if current.asr.diarize_speakers != count:
            self._settings_store.save(
                replace(current, asr=replace(current.asr, diarize_speakers=count))
            )

    # --- blokada podczas transkrypcji ----------------------------------------

    def transcription_started(self) -> None:
        """Blokuje okno na czas transkrypcji; aktywne zostaje tylko anulowanie.

        Nakładka przechwytuje mysz, a wyłączone widżety i akcje odcinają
        klawiaturę i skróty (także te o zasięgu całej aplikacji).
        """
        self._set_locked(True)
        self._autosave.pause()
        self._overlay.start()

    def transcription_finished(self) -> None:
        self._overlay.stop()
        self._set_locked(False)
        self._autosave.resume()
