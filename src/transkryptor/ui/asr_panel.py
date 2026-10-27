"""Panel lokalnego szkicu ASR: zgoda na pobranie, postęp, reguły, przegląd.

Warstwa UI łączy moduł ``asr`` (bez Qt) z wątkami ``QThread`` i widżetami.
Zgodnie z kontraktem ``asr -> ui`` wątki przekazują wyłącznie stan zadania,
hipotezę, przedziały pewności i błędy - nigdy obiekty GUI.

Panel nie zmienia dokumentu sam: gotowy szkic emituje sygnałem
``draft_ready``, a wstawienie do edytora, automatyczne reguły wybrane
checkboxami (REQ-15) i pojedyncze propozycje (ACC-12) wykonuje główne okno.

Panel jest cienkim kontenerem trzech sekcji, które układa w kolejne kroki:

- ``models`` (:class:`ModelSection`) - krok „Model”: wybór modelu
  z rejestru, pobranie za zgodą i usunięcie (REQ-10);
- ``review`` (:class:`ReviewSection`) - krok „Reguły” i lista przeglądu
  zastosowanych zmian i propozycji (REQ-16);
- ``transcription`` (:class:`TranscriptionSection`) - krok „Szkic”:
  kontekst i słownik (REQ-21), transkrypcja i lista segmentów.

Sygnały i metody publiczne panelu przekazują dalej sygnały i metody sekcji,
więc reszta interfejsu nie zależy od podziału na sekcje.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from transkryptor.asr.engine import DecodingOptions, TranscriptionResult
from transkryptor.asr.manager import ModelManager
from transkryptor.asr.models import AsrModelInfo
from transkryptor.notation.suggestions import RuleInfo, Suggestion
from transkryptor.settings import AsrSettings
from transkryptor.ui.asr_model_section import ModelSection
from transkryptor.ui.asr_review_section import ReviewSection
from transkryptor.ui.asr_transcription_section import TranscriptionSection
from transkryptor.ui.asr_widgets import divider


class AsrPanel(QWidget):
    """Panel konfiguracji modelu, pobierania i propozycji transkrypcji."""

    # Szkic do wstawienia w edytor: ``TranscriptionResult`` (z segmentami
    # i czasami - kotwice tekstu) albo sam tekst.
    draft_ready = Signal(object)
    review_item_activated = Signal(int)  # indeks pozycji listy przeglądu
    review_item_apply_requested = Signal(int)
    review_finish_requested = Signal()
    transcription_started = Signal()
    transcription_progress = Signal(float)  # ułamek nagrania 0.0-1.0
    transcription_finished = Signal()
    seek_requested = Signal(int)  # pozycja nagrania w ms
    # Wynik transkrypcji fragmentu (``TranscriptionResult``) do wstawienia
    # w miejscu kursora; nie zastępuje ostatniego szkicu całego nagrania.
    fragment_ready = Signal(object)
    result_changed = Signal()  # nowy albo odtworzony wynik ASR całego nagrania
    model_changed = Signal(str)  # klucz modelu wybranego przez użytkownika
    speakers_changed = Signal(int)  # liczba mówców wybrana w panelu; 0 - auto
    context_changed = Signal()  # kontekst nagrania lub słownik projektu

    def __init__(
        self,
        manager: ModelManager,
        audio_path_provider: Callable[[], Path | None] = lambda: None,
        transcribe_impl: Callable[..., TranscriptionResult] | None = None,
        parent=None,
        clip_provider: Callable[[], tuple[int, int] | None] = lambda: None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("asr_panel")
        self.models = ModelSection(manager, self)
        self.review = ReviewSection(self)
        self.transcription = TranscriptionSection(
            self.models, self, audio_path_provider, transcribe_impl, clip_provider
        )
        self._build_layout()
        self._forward_signals()
        self.models.status_changed.connect(self._on_model_status_changed)
        self.refresh_model_status()

    def _build_layout(self) -> None:
        content = QWidget()
        content.setObjectName("asr_panel_content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(18)
        layout.addWidget(self.models.build_step())
        layout.addWidget(self.review.build_rules_step())
        layout.addWidget(self.transcription.build_step())
        layout.addWidget(divider())
        layout.addLayout(self.transcription.build_segments_box(), stretch=2)
        layout.addLayout(self.review.build_review_box(), stretch=3)

        # Przewijanie na niskich ekranach; panel nie wymusza wysokości okna.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.setMinimumWidth(360)

    def _forward_signals(self) -> None:
        self.models.model_changed.connect(self.model_changed)
        transcription = self.transcription
        transcription.draft_ready.connect(self.draft_ready)
        transcription.transcription_started.connect(self.transcription_started)
        transcription.transcription_progress.connect(self.transcription_progress)
        transcription.transcription_finished.connect(self.transcription_finished)
        transcription.seek_requested.connect(self.seek_requested)
        transcription.fragment_ready.connect(self.fragment_ready)
        transcription.result_changed.connect(self.result_changed)
        transcription.speakers_changed.connect(self.speakers_changed)
        transcription.context_changed.connect(self.context_changed)
        self.review.review_item_activated.connect(self.review_item_activated)
        self.review.review_item_apply_requested.connect(
            self.review_item_apply_requested
        )
        self.review.review_finish_requested.connect(self.review_finish_requested)

    def _on_model_status_changed(self) -> None:
        self.transcription.update_availability()
        self.transcription.update_speakers_row()

    # --- model ---------------------------------------------------------------

    @property
    def manager(self) -> ModelManager:
        """Menedżer wybranego modelu (katalog modeli z ustawień)."""
        return self.models.manager

    @property
    def model(self) -> AsrModelInfo:
        """Model wybrany w panelu."""
        return self.models.model

    @property
    def model_dir(self) -> Path:
        return self.models.model_dir

    def refresh_model_status(self) -> None:
        """Aktualizuje opis i status modelu oraz dostępność akcji."""
        self.models.refresh_model_status()

    def diarization_ready(self) -> bool:
        return self.models.diarization_ready()

    def select_model(self, key: str) -> None:
        """Wybiera model (np. z ustawień) bez emitowania ``model_changed``."""
        self.models.select_model(key)

    def set_asr_settings(self, settings: AsrSettings) -> None:
        """Stosuje ustawienia ASR: model, katalog modeli, urządzenie, słownik."""
        self.transcription.apply_settings(settings)
        self.models.apply_settings(settings)

    def download_consent_text(self) -> str:
        return self.models.download_consent_text()

    def is_downloading(self) -> bool:
        return self.models.is_downloading()

    def cancel_download_and_wait(self, timeout_ms: int) -> bool:
        """Przerywa pobieranie i czeka na wątek (zamknięcie okna, BUG-01)."""
        return self.models.cancel_download_and_wait(timeout_ms)

    # --- transkrypcja --------------------------------------------------------

    def asr_context(self) -> tuple[str, tuple[str, ...]]:
        """Kontekst nagrania i słownik projektu (do zapisu w projekcie)."""
        return self.transcription.asr_context()

    def set_asr_context(self, prompt: str, vocabulary: tuple[str, ...]) -> None:
        self.transcription.set_asr_context(prompt, vocabulary)

    def set_context_default(self, text: str) -> None:
        self.transcription.set_context_default(text)

    def decoding_options(self) -> DecodingOptions:
        return self.transcription.decoding_options()

    def set_audio_available(self, available: bool) -> None:
        self.transcription.set_audio_available(available)

    def set_segment_preroll_ms(self, preroll_ms: int) -> None:
        self.transcription.set_segment_preroll_ms(preroll_ms)

    @property
    def last_result(self) -> TranscriptionResult | None:
        return self.transcription.last_result

    @property
    def last_model_key(self) -> str | None:
        return self.transcription.last_model_key

    def restore_result(
        self, result: TranscriptionResult | None, model_key: str | None = None
    ) -> None:
        self.transcription.restore_result(result, model_key)

    def is_transcribing(self) -> bool:
        return self.transcription.is_transcribing()

    def cancel_transcription(self) -> None:
        self.transcription.cancel_transcription()

    def shutdown(self) -> None:
        """Kończy podproces roboczy ASR (zamknięcie okna)."""
        self.transcription.shutdown()

    # --- reguły i przegląd ---------------------------------------------------

    def set_rules(self, rules: tuple[RuleInfo, ...]) -> None:
        self.review.set_rules(rules)

    def selected_rule_codes(self) -> frozenset[str]:
        return self.review.selected_rule_codes()

    def set_review_items(self, items: list[tuple[Suggestion, bool]]) -> None:
        self.review.set_review_items(items)

    def clear_review(self) -> None:
        self.review.clear_review()
