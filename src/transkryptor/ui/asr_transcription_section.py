"""Krok „Szkic” panelu ASR: kontekst, słownik, transkrypcja i segmenty.

Krok zaczyna się od danych nagrania (pole przekazane przez panel), potem
kwestionariusz, mówcy i transkrypcja z „Tylko fragment A-B”; kontekst,
słownik i rozpoznanie fragmentu w miejscu kursora są w zwiniętych „Więcej opcjach”, a segmenty - w zwiniętej liście pod krokami.

Sekcja zbiera kontekst nagrania i słownik projektu, które trafiają do
Whispera razem ze słownikiem globalnym z ustawień (REQ-21), uruchamia
transkrypcję całego nagrania albo fragmentu A-B w wątku ``TranscribeThread``
i pokazuje segmenty wyniku. Fragment trafia w miejsce kursora („Rozpoznaj
fragment A-B”) albo - przy zaznaczonym „Tylko fragment A-B” - staje się
szkicem jak całe nagranie (segmenty, „Wstaw szkic ponownie”). Kliknięcie segmentu emituje ``seek_requested``.
Model i jego katalog bierze z :class:`ModelSection`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from transkryptor import diagnostics
from transkryptor.asr.engine import (
    DIARIZED_ASR_SHARE,
    PROMPT_MAX_CHARS,
    DecodingOptions,
    SegmentResult,
    TranscriptionResult,
    build_hotwords,
    compose_prompt,
    draft_text,
    format_timestamp,
)
from transkryptor.asr.models import DIARIZATION_MODEL, AsrModelInfo, format_size
from transkryptor.asr.system import total_memory_bytes
from transkryptor.asr.worker import AsrWorker
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.settings import AsrSettings, split_vocabulary
from transkryptor.ui import icons
from transkryptor.ui.asr_model_section import ModelSection
from transkryptor.ui.asr_questionnaire import QuestionnaireBox
from transkryptor.ui.asr_speakers_box import (
    COUNT_ACTIVE,
    COUNT_DIARIZE_OFF,
    COUNT_NO_MODEL,
    COUNT_QA_LAYOUT,
    SpeakersBox,
)
from transkryptor.ui.asr_transcribe_thread import TranscribeThread
from transkryptor.ui.asr_widgets import AutoHideLabel, Collapsible, step
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props, tokens

logger = logging.getLogger(__name__)

# Segmenty poniżej tej pewności są wyróżnione jako warte uważnego odsłuchu.
LOW_CONFIDENCE = 0.6
# Czasy po VAD bywają przesunięte o ułamki sekundy - start nieco wcześniej.
DEFAULT_SEGMENT_PREROLL_MS = 500


class TranscriptionSection(QObject):
    """Kontekst i słownik, transkrypcja z postępem i anulowaniem, segmenty."""

    # Szkic do wstawienia w edytor: ``TranscriptionResult`` (z segmentami
    # i czasami - kotwice tekstu) albo sam tekst.
    draft_ready = Signal(object)
    transcription_started = Signal()
    transcription_progress = Signal(float)  # ułamek nagrania 0.0-1.0
    transcription_finished = Signal()
    seek_requested = Signal(int)  # pozycja nagrania w ms
    # Wynik transkrypcji fragmentu (``TranscriptionResult``) do wstawienia
    # w miejscu kursora; nie zastępuje ostatniego szkicu całego nagrania.
    fragment_ready = Signal(object)
    result_changed = Signal()  # nowy albo odtworzony wynik ASR całego nagrania
    speakers_changed = Signal(int)  # liczba mówców wybrana w panelu; 0 - auto
    speakers_edit_requested = Signal()  # „Mówcy…” - edycja listy mówców
    qa_layout_changed = Signal(bool)  # układ „pytanie - odpowiedź” w panelu
    context_changed = Signal()  # kontekst nagrania lub słownik projektu

    def __init__(
        self,
        models: ModelSection,
        dialog_parent: QWidget,
        audio_path_provider: Callable[[], Path | None],
        transcribe_impl: Callable[..., TranscriptionResult] | None,
        clip_provider: Callable[[], tuple[int, int] | None],
    ) -> None:
        super().__init__(dialog_parent)
        self._models = models
        self._parent = dialog_parent
        self._audio_path_provider = audio_path_provider
        # Zakres fragmentu (ms) - punkty A-B paska odtwarzacza.
        self._clip_provider = clip_provider
        # Wynik trafia w miejsce kursora zamiast stać się szkicem.
        self._fragment_mode = False
        # Domyślnie podproces roboczy (PERF-04): model zostaje w pamięci,
        # a „Anuluj” kończy pracę od razu. Testy podstawiają imitację.
        self._worker: AsrWorker | None = None
        if transcribe_impl is None:
            self._worker = AsrWorker()
            transcribe_impl = self._worker.transcribe
        self._transcribe_impl = transcribe_impl
        self._transcribe_thread: TranscribeThread | None = None
        self._transcribe_started = time.monotonic()
        self._last_draft = ""
        self._last_result: TranscriptionResult | None = None
        self._last_model_key: str | None = None
        self._running_model_key: str | None = None
        self._audio_available = False
        self._segment_preroll_ms = DEFAULT_SEGMENT_PREROLL_MS
        self._device = "auto"
        self._chunked = False
        self._word_timestamps = True
        self._verbatim = True
        self._diarize = True
        self._diarize_speakers = 0
        self._qa_layout = False
        self._diarizing = False
        self._global_vocabulary: tuple[str, ...] = ()
        self._context_default = ""
        self._updating = False

        self._build_context_widgets()
        self._build_transcribe_widgets()
        self.context_edit.textChanged.connect(self._on_context_edited)
        self.vocabulary_edit.textChanged.connect(self._on_context_edited)
        self.speakers_box.count_changed.connect(self._on_speakers_selected)
        self.speakers_box.edit_requested.connect(self.speakers_edit_requested)
        self.transcribe_button.clicked.connect(self._on_transcribe_clicked)
        self.clip_only_check.toggled.connect(self._update_transcribe_label)
        self.fragment_button.clicked.connect(self._on_fragment_clicked)
        self.cancel_transcribe_button.clicked.connect(self.cancel_transcription)
        self.reinsert_draft_button.clicked.connect(
            lambda: self.draft_ready.emit(
                self._last_result if self._last_result is not None else self._last_draft
            )
        )
        self.segments_list.itemClicked.connect(self._on_segment_activated)
        self.segments_list.itemActivated.connect(self._on_segment_activated)
        self._update_context_counter()
        self._update_vocabulary_hint()

    def _build_context_widgets(self) -> None:
        self.context_edit = QLineEdit()
        self.context_edit.setMaxLength(PROMPT_MAX_CHARS)
        self.context_edit.setPlaceholderText(tr("asr.context.placeholder"))
        self.context_edit.setToolTip(tr("asr.context.tooltip"))
        self.context_counter = QLabel()
        set_props(self.context_counter, role="muted")
        self.vocabulary_edit = QPlainTextEdit()
        self.vocabulary_edit.setPlaceholderText(tr("asr.vocabulary.placeholder"))
        self.vocabulary_edit.setToolTip(tr("asr.vocabulary.tooltip"))
        self.vocabulary_edit.setTabChangesFocus(True)
        self.vocabulary_edit.setFixedHeight(64)
        self.vocabulary_hint = QLabel()
        self.vocabulary_hint.setWordWrap(True)
        set_props(self.vocabulary_hint, role="muted")
        self.questionnaire_box = QuestionnaireBox()
        self.questionnaire_box.changed.connect(self.context_changed)
        # Rozmówcy i liczba mówców - widoczne zawsze (zgł. #56); zmiana
        # liczby trafia do ustawień (jak wybór modelu).
        self.speakers_box = SpeakersBox()
        self.qa_layout_check = QCheckBox(tr("asr.qa_layout"))
        self.qa_layout_check.setObjectName("asr_qa_layout_check")
        self.qa_layout_check.setToolTip(tr("asr.qa_layout.tooltip"))
        self.qa_layout_check.toggled.connect(self._on_qa_layout_toggled)

    def _build_transcribe_widgets(self) -> None:
        self.device_label = AutoHideLabel()
        self.device_label.setWordWrap(True)
        set_props(self.device_label, role="muted")
        self.transcribe_button = QPushButton(tr("asr.transcribe"))
        set_props(self.transcribe_button, variant="primary")
        icons.set_icon(self.transcribe_button, "sparkles", "on_accent", "text_muted")
        self.transcribe_button.setIconSize(icons.ICON_SIZE)
        self.clip_only_check = QCheckBox(tr("asr.clip_only"))
        self.clip_only_check.setObjectName("asr_clip_only_check")
        self.clip_only_check.setToolTip(tr("asr.clip_only.tooltip"))
        self.fragment_button = QPushButton(tr("asr.fragment"))
        icons.set_icon(self.fragment_button, "loop", "text", "text_muted")
        self.fragment_button.setToolTip(tr("asr.fragment.tooltip"))
        self.cancel_transcribe_button = QPushButton(tr("loading.cancel"))
        set_props(self.cancel_transcribe_button, variant="danger")
        self.cancel_transcribe_button.setVisible(False)
        self.transcribe_status_label = AutoHideLabel()
        self.transcribe_status_label.setWordWrap(True)
        set_props(self.transcribe_status_label, role="muted")
        self.reinsert_draft_button = QPushButton(tr("asr.reinsert"))
        icons.set_icon(self.reinsert_draft_button, "redo", "text", "text_muted")
        self.reinsert_draft_button.setToolTip(tr("asr.reinsert.tooltip"))
        self.reinsert_draft_button.setEnabled(False)
        self.segments_list = QListWidget()
        self.segments_list.setObjectName("asr_segments_list")
        self.segments_list.setToolTip(tr("asr.segments.tooltip"))
        self.segments_list.setMinimumHeight(110)
        self.segments_list.setWordWrap(True)
        self.segments_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def build_step(self, recording: QWidget) -> QWidget:
        """Krok 3 panelu: dane nagrania, kwestionariusz, mówcy i transkrypcja.

        „Tylko fragment A-B” stoi pod przyciskiem szkicu, który zmienia; kontekst,
        słownik i „Rozpoznaj fragment A-B” są w zwiniętych „Więcej opcjach” -
        zwykle wystarczają dane nagrania i kwestionariusz (zgł. #57).
        """
        transcribe_row = QHBoxLayout()
        transcribe_row.addWidget(self.transcribe_button, stretch=1)
        transcribe_row.addWidget(self.cancel_transcribe_button)
        context_header = QHBoxLayout()
        context_header.addWidget(QLabel(tr("asr.context")), stretch=1)
        context_header.addWidget(self.context_counter)
        self.more_options = Collapsible(
            "asr_more",
            tr("asr.more"),
            [
                context_header,
                self.context_edit,
                QLabel(tr("asr.vocabulary")),
                self.vocabulary_edit,
                self.vocabulary_hint,
                self.fragment_button,
            ],
        )
        self.more_options.toggle.setToolTip(tr("asr.more.tooltip"))
        return step(
            "3",
            tr("asr.step.draft"),
            [
                QLabel(tr("asr.recording")),
                recording,
                QLabel(tr("asr.questionnaire")),
                self.questionnaire_box,
                self.speakers_box,
                self.qa_layout_check,
                transcribe_row,
                self.clip_only_check,
                self.transcribe_status_label,
                self.device_label,
                self.reinsert_draft_button,
                self.more_options,
            ],
        )

    def build_segments_box(self) -> Collapsible:
        """Zwinięta lista segmentów ostatniego szkicu pod krokami panelu."""
        box = Collapsible("asr_segments", tr("asr.segments"), [self.segments_list])
        box.count_rows(self.segments_list.model())
        return box

    # --- ustawienia ----------------------------------------------------------

    def apply_settings(self, settings: AsrSettings) -> None:
        """Urządzenie, dzielenie na fragmenty, mówcy i słownik globalny."""
        self._device = settings.device
        self._chunked = settings.chunked
        self._word_timestamps = settings.word_timestamps
        self._verbatim = settings.verbatim
        self._diarize = settings.diarize
        self._diarize_speakers = settings.diarize_speakers
        self._qa_layout = settings.qa_layout
        self.qa_layout_check.blockSignals(True)
        self.qa_layout_check.setChecked(settings.qa_layout)
        self.qa_layout_check.blockSignals(False)
        self._global_vocabulary = settings.vocabulary_words
        self._update_vocabulary_hint()
        self.update_speakers()

    def update_speakers(self) -> None:
        """Liczba mówców: aktywna tylko, gdy podział na mówców zadziała."""
        if self._qa_layout:
            reason = COUNT_QA_LAYOUT
        elif not self._diarize:
            reason = COUNT_DIARIZE_OFF
        elif not self._models.diarization_ready():
            reason = COUNT_NO_MODEL
        else:
            reason = COUNT_ACTIVE
        self.speakers_box.set_count_state(reason)
        self.speakers_box.set_count(self._diarize_speakers)

    def set_speakers_legend(self, text: str) -> None:
        """Legenda mówców dokumentu pokazywana przy liczbie mówców."""
        self.speakers_box.set_legend(text)

    def _on_speakers_selected(self, count: int) -> None:
        self._diarize_speakers = count
        self.speakers_changed.emit(count)

    def _on_qa_layout_toggled(self, checked: bool) -> None:
        self._qa_layout = checked
        self.update_speakers()
        self.qa_layout_changed.emit(checked)

    def set_segment_preroll_ms(self, preroll_ms: int) -> None:
        """Ile przed początkiem segmentu startuje odsłuch (z ustawień)."""
        self._segment_preroll_ms = max(0, preroll_ms)

    # --- kontekst i słownik --------------------------------------------------

    def asr_context(self) -> tuple[str, tuple[str, ...]]:
        """Kontekst nagrania i słownik projektu (do zapisu w projekcie)."""
        return (
            self.context_edit.text().strip(),
            split_vocabulary(self.vocabulary_edit.toPlainText()),
        )

    def set_asr_context(self, prompt: str, vocabulary: tuple[str, ...]) -> None:
        """Odtwarza kontekst i słownik projektu bez emitowania zmian."""
        self._updating = True
        try:
            self.context_edit.setText(prompt[:PROMPT_MAX_CHARS])
            self.vocabulary_edit.setPlainText("\n".join(vocabulary))
        finally:
            self._updating = False
        self._context_default = ""
        self._update_context_counter()

    def set_context_default(self, text: str) -> None:
        """Podpowiedź kontekstu z metryczki.

        Zastępuje pole tylko, gdy jest puste albo zawiera poprzednią
        podpowiedź - tekst wpisany przez użytkownika zostaje.
        """
        text = text[:PROMPT_MAX_CHARS]
        current = self.context_edit.text()
        if current and current != self._context_default:
            return
        self._context_default = text
        if current != text:
            self._updating = True
            try:
                self.context_edit.setText(text)
            finally:
                self._updating = False
            self._update_context_counter()
            self.context_changed.emit()

    def decoding_options(self) -> DecodingOptions:
        """Parametry dla Whispera: urządzenie, kontekst i suma słowników.

        Podział na mówców - gdy włączony w ustawieniach i model jest pobrany.
        """
        prompt, vocabulary = self.asr_context()
        diarization = self._models.manager.with_model(DIARIZATION_MODEL)
        # Układ „pytanie - odpowiedź” zastępuje podział według głosu.
        diarize = self._diarize and not self._qa_layout and diarization.is_downloaded()
        return DecodingOptions(
            device=self._device,
            initial_prompt=compose_prompt(prompt, verbatim=self._verbatim),
            hotwords=build_hotwords(self._global_vocabulary, vocabulary),
            chunked=self._chunked,
            word_timestamps=self._word_timestamps,
            diarize=diarize,
            diarization_dir=diarization.model_dir if diarize else None,
            speakers=self._diarize_speakers or None,
        )

    def _on_context_edited(self) -> None:
        self._update_context_counter()
        if not self._updating:
            self.context_changed.emit()

    def _update_context_counter(self) -> None:
        self.context_counter.setText(
            f"{len(self.context_edit.text())}/{PROMPT_MAX_CHARS}"
        )

    def _update_vocabulary_hint(self) -> None:
        count = len(self._global_vocabulary)
        self.vocabulary_hint.setText(
            tr("asr.vocabulary.global", count=count, limit=PROMPT_MAX_CHARS)
        )

    # --- nagranie i segmenty -------------------------------------------------

    def set_audio_available(self, available: bool) -> None:
        """Informuje o zmianie nagrania (nowe nagranie albo brak).

        Lista segmentów jest czyszczona: segmenty poprzedniego nagrania nie
        mogą przewijać nowego pliku (ACC-20).
        """
        self._audio_available = available
        self.segments_list.clear()
        self.update_availability()

    def update_availability(self) -> None:
        available = (
            self._models.is_downloaded()
            and self._audio_available
            and self._transcribe_thread is None
        )
        self.transcribe_button.setEnabled(available)
        self.fragment_button.setEnabled(available)

    def _on_segment_activated(self, item: QListWidgetItem) -> None:
        start_ms = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(start_ms, int):
            self.seek_requested.emit(max(0, start_ms - self._segment_preroll_ms))

    def _on_segment_ready(self, segment: SegmentResult) -> None:
        item = QListWidgetItem(
            f"{format_timestamp(segment.start_s)}-{format_timestamp(segment.end_s)} "
            f"({segment.confidence:.0%}) {segment.text.strip()}"
        )
        item.setData(Qt.ItemDataRole.UserRole, int(segment.start_s * 1000))
        if segment.confidence < LOW_CONFIDENCE:
            # Ikona obok koloru: niska pewność widoczna bez rozróżniania barw.
            item.setIcon(icons.icon("alert", tokens().warning))
            item.setForeground(QColor(tokens().warning))
            item.setToolTip(tr("asr.low_confidence.tooltip"))
        self.segments_list.addItem(item)

    # --- transkrypcja --------------------------------------------------------

    def _update_transcribe_label(self, clip_only: bool) -> None:
        self.transcribe_button.setText(
            tr("asr.transcribe.clip" if clip_only else "asr.transcribe")
        )

    def _on_transcribe_clicked(self) -> None:
        """Szkic całego nagrania albo - przy „Tylko fragment A-B” - pętli."""
        if not self.clip_only_check.isChecked():
            self._start_transcription(None, fragment=False)
            return
        clip = self._loop_clip()
        if clip is not None:
            self._start_transcription(clip, fragment=False)

    def _on_fragment_clicked(self) -> None:
        """Transkrypcja fragmentu A-B w miejsce kursora (propozycja 10A)."""
        clip = self._loop_clip()
        if clip is not None:
            self._start_transcription(clip, fragment=True)

    def _loop_clip(self) -> tuple[float, float] | None:
        """Punkty A-B pętli w sekundach; bez nich - komunikat w panelu."""
        clip = self._clip_provider()
        if clip is None:
            self.transcribe_status_label.setText(tr("asr.fragment.no_range"))
            return None
        start_ms, end_ms = clip
        return start_ms / 1000, end_ms / 1000

    def _start_transcription(
        self, clip: tuple[float, float] | None, *, fragment: bool
    ) -> None:
        audio_path = self._audio_path_provider()
        if audio_path is None:
            self.transcribe_status_label.setText(tr("asr.no_audio"))
            return
        if not self._confirm_memory():
            return
        self._fragment_mode = fragment
        self.transcribe_button.setEnabled(False)
        self.fragment_button.setEnabled(False)
        self.cancel_transcribe_button.setVisible(True)
        self.transcribe_status_label.setText(tr("asr.transcribing"))
        self.device_label.setText("")
        if not self._fragment_mode:
            self.segments_list.clear()
            self.reinsert_draft_button.setEnabled(False)
        options = replace(self.decoding_options(), clip=clip)
        self._diarizing = options.diarizes
        model = self._models.model
        _log_start(model, audio_path, options, clip)
        self._transcribe_started = time.monotonic()
        thread = TranscribeThread(
            audio_path,
            self._models.model_dir,
            self._transcribe_impl,
            self,
            model=model,
            options=options,
        )
        if not self._fragment_mode:
            thread.segment_ready.connect(self._on_segment_ready)
        thread.progressed.connect(self._on_transcribe_progress)
        thread.succeeded.connect(self._on_transcribe_succeeded)
        thread.failed.connect(self._on_transcribe_failed)
        thread.cancelled.connect(self._on_transcribe_cancelled)
        self._transcribe_thread = thread
        self._running_model_key = model.key
        self._models.set_transcribing(True)
        thread.start()
        self.transcription_started.emit()

    def _confirm_memory(self) -> bool:
        """Ostrzega, gdy model wymaga więcej RAM, niż ma komputer."""
        model = self._models.model
        memory = total_memory_bytes()
        if memory is None or memory >= model.min_ram_bytes:
            return True
        answer = QMessageBox.question(
            self._parent,
            tr("asr.memory.title"),
            tr(
                "asr.memory.warning",
                model=model.display_name,
                required=format_size(model.min_ram_bytes),
                available=format_size(memory),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_transcribe_progress(self, fraction: float) -> None:
        key = (
            "asr.diarizing.percent"
            if self._diarizing and fraction > DIARIZED_ASR_SHARE
            else "asr.transcribing.percent"
        )
        self.transcribe_status_label.setText(tr(key, percent=int(fraction * 100)))
        self.transcription_progress.emit(fraction)

    def _on_transcribe_succeeded(self, result: TranscriptionResult) -> None:
        logger.info(
            "Transcription finished in %.1f s: %d segments, device=%s%s, "
            "speakers=%d",
            self._transcription_seconds(),
            len(result.segments),
            result.device,
            f" (GPU fallback: {result.device_note})" if result.device_note else "",
            len({s.speaker for s in result.segments if s.speaker is not None}),
        )
        self._finish_transcribe()
        if self._fragment_mode:
            self.device_label.setText(_device_text(result))
            if not result.text.strip():
                self.transcribe_status_label.setText(tr("asr.no_speech"))
                return
            self.transcribe_status_label.setText(tr("asr.fragment.ready"))
            self.fragment_ready.emit(result)
            return
        self._last_draft = draft_text(result)
        self._last_result = result
        self._last_model_key = self._running_model_key
        self.result_changed.emit()
        self.device_label.setText(_device_text(result))
        if not result.text.strip():
            self.transcribe_status_label.setText(tr("asr.no_speech"))
            return
        self.reinsert_draft_button.setEnabled(True)
        self.transcribe_status_label.setText(tr("asr.draft_ready"))
        self.draft_ready.emit(result)

    def _on_transcribe_failed(self, error: AppError) -> None:
        logger.warning(
            "Transcription failed after %.1f s", self._transcription_seconds()
        )
        self._finish_transcribe()
        self.transcribe_status_label.setText(tr("asr.failed"))
        show_error(self._parent, tr("asr.failed.title"), error)

    def _on_transcribe_cancelled(self) -> None:
        logger.info(
            "Transcription cancelled after %.1f s", self._transcription_seconds()
        )
        self._finish_transcribe()
        self.transcribe_status_label.setText(tr("asr.cancelled"))

    def _transcription_seconds(self) -> float:
        return time.monotonic() - self._transcribe_started

    def _finish_transcribe(self) -> None:
        thread = self._transcribe_thread
        self._transcribe_thread = None
        if thread is not None:
            if not thread.isFinished():
                thread.wait(5000)
            thread.deleteLater()
        self.cancel_transcribe_button.setVisible(False)
        self.cancel_transcribe_button.setEnabled(True)
        self._models.set_transcribing(False)
        self.update_availability()
        self.transcription_finished.emit()

    @property
    def last_result(self) -> TranscriptionResult | None:
        """Ostatni udany wynik ASR (do zapisu w projekcie)."""
        return self._last_result

    @property
    def last_model_key(self) -> str | None:
        """Klucz modelu, którym obliczono ostatni wynik (None - nieznany)."""
        return self._last_model_key if self._last_result is not None else None

    def restore_result(
        self, result: TranscriptionResult | None, model_key: str | None = None
    ) -> None:
        """Odtwarza wynik ASR z projektu: segmenty i „Wstaw szkic ponownie”.

        Nie emituje ``draft_ready`` - tekst dokumentu pochodzi z projektu.
        """
        self.segments_list.clear()
        self.device_label.setText("")
        self._last_result = result
        self._last_model_key = model_key
        self._last_draft = draft_text(result) if result is not None else ""
        if result is not None:
            for segment in result.segments:
                self._on_segment_ready(segment)
        self.reinsert_draft_button.setEnabled(bool(self._last_draft.strip()))
        self.transcribe_status_label.setText(
            tr("asr.restored") if self._last_draft.strip() else ""
        )
        self.result_changed.emit()

    def is_transcribing(self) -> bool:
        return self._transcribe_thread is not None

    def shutdown(self) -> None:
        """Kończy podproces roboczy ASR (zamknięcie okna)."""
        if self._worker is not None:
            self._worker.shutdown()

    def cancel_transcription(self) -> None:
        """Prosi o przerwanie trwającej transkrypcji (przycisk albo nakładka)."""
        if self._transcribe_thread is not None:
            self._transcribe_thread.cancel()
            self.cancel_transcribe_button.setEnabled(False)


def _log_start(
    model: AsrModelInfo,
    audio_path: Path,
    options: DecodingOptions,
    clip: tuple[float, float] | None,
) -> None:
    # Bez treści kontekstu i słownika - to dane z wywiadu.
    logger.info(
        "Transcription started: model=%s, audio=%s, device=%s, chunked=%s, "
        "word_timestamps=%s, diarize=%s, speakers=%s, clip=%s, prompt=%s, "
        "hotwords=%s",
        model.key,
        diagnostics.file_summary(audio_path),
        options.device,
        options.chunked,
        options.word_timestamps,
        options.diarizes,
        options.speakers or "auto",
        "none" if clip is None else f"{clip[1] - clip[0]:.1f} s",
        bool(options.initial_prompt),
        bool(options.hotwords),
    )


def _device_text(result: TranscriptionResult) -> str:
    """Informacja, na czym liczono szkic; przejście z GPU na CPU (ACC-37)."""
    if result.device_note:
        text = tr("asr.device.fallback", reason=result.device_note)
    elif result.device == "cuda":
        text = tr("asr.device.gpu")
    else:
        text = tr("asr.device.cpu")
    if result.diarization_note:
        text += "\n" + tr("asr.diarize.failed", reason=result.diarization_note)
    return text
