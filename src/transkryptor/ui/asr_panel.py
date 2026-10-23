"""Panel lokalnego szkicu ASR: zgoda na pobranie, postęp, reguły, przegląd.

Warstwa UI łączy moduł ``asr`` (bez Qt) z wątkami ``QThread`` i widżetami.
Zgodnie z kontraktem ``asr -> ui`` wątki przekazują wyłącznie stan zadania,
hipotezę, przedziały pewności i błędy — nigdy obiekty GUI.

Panel nie zmienia dokumentu sam: gotowy szkic emituje sygnałem
``draft_ready``, a wstawienie do edytora, automatyczne reguły wybrane
checkboxami (REQ-15) i pojedyncze propozycje (ACC-12) wykonuje główne okno.
Panel pokazuje listę zastosowanych zmian i propozycji do przeglądu (REQ-16).
Kliknięcie segmentu emituje ``seek_requested`` — okno przewija nagranie.

Krok „Model” pozwala wybrać model z rejestru (``asr.models.MODELS``), pobrać
go za zgodą albo usunąć (REQ-10). Krok „Szkic” zbiera kontekst nagrania
i słownik projektu, które trafiają do Whispera razem ze słownikiem
globalnym z ustawień (REQ-21).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor import diagnostics
from transkryptor.asr import engine
from transkryptor.asr.engine import (
    DIARIZED_ASR_SHARE,
    PROMPT_MAX_CHARS,
    DecodingOptions,
    SegmentResult,
    TranscriptionResult,
    build_hotwords,
    draft_text,
    format_timestamp,
)
from transkryptor.asr.manager import DownloadCancelled, ModelManager
from transkryptor.asr.models import (
    DIARIZATION_MODEL,
    MODELS,
    AsrModelInfo,
    format_size,
    model_by_key,
)
from transkryptor.asr.system import total_memory_bytes
from transkryptor.asr.worker import AsrWorker
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.suggestions import (
    RuleInfo,
    Suggestion,
    default_rules,
    rule_infos,
)
from transkryptor.settings import AsrSettings, split_vocabulary
from transkryptor.ui import icons
from transkryptor.ui.messages import log_user_error
from transkryptor.ui.theme import set_props, tokens

logger = logging.getLogger(__name__)

APPLIED_MARK = "✓"
PENDING_MARK = "○"
# Segmenty poniżej tej pewności są wyróżnione jako warte uważnego odsłuchu.
LOW_CONFIDENCE = 0.6
# Czasy po VAD bywają przesunięte o ułamki sekundy — start nieco wcześniej.
DEFAULT_SEGMENT_PREROLL_MS = 500

# Indeks górny w etykietach listy (lista nie obsługuje rich text).
_SUPERSCRIPT_LETTERS = str.maketrans("mnu", "ᵐⁿᵘ")


class DownloadThread(QThread):
    """Pobieranie modelu w tle z postępem bajtowym i anulowaniem."""

    progressed = Signal(int, object, str)  # pobrane, całość | None, plik
    succeeded = Signal()
    failed = Signal(object)  # ModelDownloadError
    cancelled = Signal()

    def __init__(self, manager: ModelManager, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._cancel_requested = False

    def cancel(self) -> None:
        """Prosi o kooperacyjne przerwanie pobierania."""
        self._cancel_requested = True

    def run(self) -> None:
        try:
            self._manager.download(
                on_progress=lambda done, total, name: self.progressed.emit(
                    done, total, name
                ),
                should_cancel=lambda: self._cancel_requested,
            )
        except DownloadCancelled:
            self.cancelled.emit()
        except AppError as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit()


class TranscribeThread(QThread):
    """Transkrypcja w tle; anulowanie sprawdzane między segmentami."""

    segment_ready = Signal(object)  # SegmentResult
    progressed = Signal(float)  # ułamek nagrania 0.0–1.0
    succeeded = Signal(object)  # TranscriptionResult
    failed = Signal(object)  # AppError
    cancelled = Signal()

    def __init__(
        self,
        audio_path: Path,
        model_dir: Path,
        transcribe_impl: Callable[..., TranscriptionResult] = engine.transcribe,
        parent=None,
        *,
        model: AsrModelInfo | None = None,
        options: DecodingOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self._audio_path = audio_path
        self._model_dir = model_dir
        self._transcribe_impl = transcribe_impl
        self._model = model
        self._options = options
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = self._transcribe_impl(
                self._audio_path,
                self._model_dir,
                should_cancel=lambda: self._cancel_requested,
                on_segment=lambda segment: self.segment_ready.emit(segment),
                on_progress=lambda fraction: self.progressed.emit(fraction),
                **self._extra_arguments(),
            )
        except engine.TranscriptionCancelled:
            self.cancelled.emit()
        except AppError as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)

    def _extra_arguments(self) -> dict[str, object]:
        extra: dict[str, object] = {}
        if self._model is not None:
            extra["model"] = self._model
        if self._options is not None:
            extra["options"] = self._options
        return extra


class AsrPanel(QWidget):
    """Panel konfiguracji modelu, pobierania i propozycji transkrypcji."""

    # Szkic do wstawienia w edytor: ``TranscriptionResult`` (z segmentami
    # i czasami — kotwice tekstu) albo sam tekst.
    draft_ready = Signal(object)
    review_item_activated = Signal(int)  # indeks pozycji listy przeglądu
    review_item_apply_requested = Signal(int)
    review_finish_requested = Signal()
    transcription_started = Signal()
    transcription_progress = Signal(float)  # ułamek nagrania 0.0–1.0
    transcription_finished = Signal()
    seek_requested = Signal(int)  # pozycja nagrania w ms
    # Wynik transkrypcji fragmentu (``TranscriptionResult``) do wstawienia
    # w miejscu kursora; nie zastępuje ostatniego szkicu całego nagrania.
    fragment_ready = Signal(object)
    result_changed = Signal()  # nowy albo odtworzony wynik ASR całego nagrania
    model_changed = Signal(str)  # klucz modelu wybranego przez użytkownika
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
        self._manager = manager
        self._audio_path_provider = audio_path_provider
        # Zakres fragmentu (ms) — punkty A–B paska odtwarzacza.
        self._clip_provider = clip_provider
        self._clip_mode = False
        # Domyślnie podproces roboczy (PERF-04): model zostaje w pamięci,
        # a „Anuluj” kończy pracę od razu. Testy podstawiają imitację.
        self._worker: AsrWorker | None = None
        if transcribe_impl is None:
            self._worker = AsrWorker()
            transcribe_impl = self._worker.transcribe
        self._transcribe_impl = transcribe_impl
        self._download_thread: DownloadThread | None = None
        self._transcribe_thread: TranscribeThread | None = None
        self._transcribe_started = time.monotonic()
        self._review_applied: list[bool] = []
        self._last_draft = ""
        self._last_result: TranscriptionResult | None = None
        self._last_model_key: str | None = None
        self._running_model_key: str | None = None
        self._audio_available = False
        self._segment_preroll_ms = DEFAULT_SEGMENT_PREROLL_MS
        self._device = "auto"
        self._chunked = False
        self._word_timestamps = True
        self._diarize = True
        self._diarize_speakers = 0
        self._diarizing = False
        # Katalog modeli z ostatnio zastosowanych ustawień (None — jeszcze
        # nie stosowano; do tego czasu obowiązuje katalog menedżera).
        self._models_root_setting: str | None = None
        self._global_vocabulary: tuple[str, ...] = ()
        self._context_default = ""
        self._updating = False

        self.setObjectName("asr_panel")
        self.model_combo = QComboBox()
        self.model_combo.setToolTip(tr("asr.model.choose.tooltip"))
        for model in MODELS:
            self.model_combo.addItem(model.display_name, model.key)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        set_props(self.info_label, role="muted")
        self.model_status_label = QLabel()
        self.model_status_label.setWordWrap(True)
        set_props(self.model_status_label, role="status")
        self.download_button = QPushButton(tr("asr.download"))
        set_props(self.download_button, variant="primary")
        icons.set_icon(self.download_button, "download", "on_accent", "text_muted")
        self.download_progress = QProgressBar()
        self.download_progress.setTextVisible(False)
        self.download_progress.setVisible(False)
        self.cancel_download_button = QPushButton(tr("asr.download.cancel"))
        set_props(self.cancel_download_button, variant="danger")
        self.cancel_download_button.setVisible(False)
        self.delete_model_button = QPushButton(tr("asr.delete"))
        set_props(self.delete_model_button, variant="ghost")
        self.delete_model_button.setToolTip(tr("asr.delete.tooltip"))

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
        self.device_label = _AutoHideLabel()
        self.device_label.setWordWrap(True)
        set_props(self.device_label, role="muted")

        self.transcribe_button = QPushButton(tr("asr.transcribe"))
        set_props(self.transcribe_button, variant="primary")
        icons.set_icon(self.transcribe_button, "sparkles", "on_accent", "text_muted")
        self.transcribe_button.setIconSize(icons.ICON_SIZE)
        self.fragment_button = QPushButton(tr("asr.fragment"))
        icons.set_icon(self.fragment_button, "loop", "text", "text_muted")
        self.fragment_button.setToolTip(tr("asr.fragment.tooltip"))
        self.cancel_transcribe_button = QPushButton(tr("loading.cancel"))
        set_props(self.cancel_transcribe_button, variant="danger")
        self.cancel_transcribe_button.setVisible(False)
        self.transcribe_status_label = _AutoHideLabel()
        self.transcribe_status_label.setWordWrap(True)
        set_props(self.transcribe_status_label, role="muted")
        self.reinsert_draft_button = QPushButton(tr("asr.reinsert"))
        icons.set_icon(self.reinsert_draft_button, "redo", "text", "text_muted")
        self.reinsert_draft_button.setToolTip(tr("asr.reinsert.tooltip"))
        self.reinsert_draft_button.setEnabled(False)

        self.rule_checkboxes: dict[str, QCheckBox] = {}
        rules_layout = QVBoxLayout()
        rules_layout.setSpacing(2)
        self._rules_layout = rules_layout

        self.segments_list = QListWidget()
        self.segments_list.setToolTip(tr("asr.segments.tooltip"))
        self.segments_list.setMinimumHeight(110)
        self.segments_list.setWordWrap(True)
        self.segments_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.suggestions_list = QListWidget()
        self.suggestions_list.setToolTip(
            tr("asr.review.tooltip", applied=APPLIED_MARK, pending=PENDING_MARK)
        )
        self.suggestions_list.setMinimumHeight(130)
        self.suggestions_list.setWordWrap(True)
        self.suggestions_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.apply_suggestion_button = QPushButton(tr("asr.review.apply"))
        icons.set_icon(self.apply_suggestion_button, "check", "text", "text_muted")
        self.apply_suggestion_button.setEnabled(False)
        self.finish_review_button = QPushButton(tr("asr.review.finish"))
        set_props(self.finish_review_button, variant="ghost")
        self.finish_review_button.setToolTip(tr("asr.review.finish.tooltip"))
        self.finish_review_button.setEnabled(False)

        # Krok 1: model.
        download_row = QHBoxLayout()
        download_row.addWidget(self.download_button)
        download_row.addWidget(self.cancel_download_button)
        download_row.addStretch(1)
        download_row.addWidget(self.delete_model_button)
        model_step = _step(
            "1",
            tr("asr.step.model"),
            [
                self.model_combo,
                self.info_label,
                self.model_status_label,
                download_row,
                self.download_progress,
            ],
        )
        # Krok 2: reguły.
        rules_hint = QLabel(tr("asr.rules.hint"))
        rules_hint.setWordWrap(True)
        set_props(rules_hint, role="muted")
        # Reguły są zwinięte do podsumowania: rozwinięte wypychały listę
        # przeglądu poza ekran na typowej wysokości okna.
        self.rules_toggle = QToolButton()
        self.rules_toggle.setObjectName("rules_toggle")
        self.rules_toggle.setCheckable(True)
        self.rules_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.rules_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.rules_details = QWidget()
        details_layout = QVBoxLayout(self.rules_details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)
        details_layout.addWidget(rules_hint)
        details_layout.addLayout(rules_layout)
        self.rules_details.setVisible(False)
        self.rules_toggle.toggled.connect(self._on_rules_toggled)
        self.set_rules(rule_infos(default_rules()))
        rules_step = _step(
            "2",
            tr("asr.step.rules"),
            [self.rules_toggle, self.rules_details],
        )
        # Krok 3: szkic.
        transcribe_row = QHBoxLayout()
        transcribe_row.addWidget(self.transcribe_button, stretch=1)
        transcribe_row.addWidget(self.cancel_transcribe_button)
        context_header = QHBoxLayout()
        context_header.addWidget(QLabel(tr("asr.context")), stretch=1)
        context_header.addWidget(self.context_counter)
        draft_step = _step(
            "3",
            tr("asr.step.draft"),
            [
                context_header,
                self.context_edit,
                QLabel(tr("asr.vocabulary")),
                self.vocabulary_edit,
                self.vocabulary_hint,
                transcribe_row,
                self.fragment_button,
                self.transcribe_status_label,
                self.device_label,
                self.reinsert_draft_button,
            ],
        )

        review_row = QHBoxLayout()
        review_row.addWidget(self.apply_suggestion_button)
        review_row.addStretch(1)
        review_row.addWidget(self.finish_review_button)

        content = QWidget()
        content.setObjectName("asr_panel_content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(18)
        layout.addWidget(model_step)
        layout.addWidget(rules_step)
        layout.addWidget(draft_step)
        layout.addWidget(_divider())
        segments_box = QVBoxLayout()
        segments_box.setSpacing(6)
        segments_box.addWidget(_section_label(tr("asr.segments")))
        segments_box.addWidget(self.segments_list, stretch=1)
        layout.addLayout(segments_box, stretch=2)
        review_box = QVBoxLayout()
        review_box.setSpacing(6)
        review_box.addWidget(_section_label(tr("asr.review")))
        review_box.addWidget(self.suggestions_list, stretch=1)
        review_box.addLayout(review_row)
        layout.addLayout(review_box, stretch=3)

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

        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        self.delete_model_button.clicked.connect(self._on_delete_clicked)
        self.context_edit.textChanged.connect(self._on_context_edited)
        self.vocabulary_edit.textChanged.connect(self._on_context_edited)
        self.download_button.clicked.connect(self._on_download_clicked)
        self.cancel_download_button.clicked.connect(self._on_cancel_download)
        self.transcribe_button.clicked.connect(self._on_transcribe_clicked)
        self.fragment_button.clicked.connect(self._on_fragment_clicked)
        self.cancel_transcribe_button.clicked.connect(self._on_cancel_transcribe)
        self.reinsert_draft_button.clicked.connect(
            lambda: self.draft_ready.emit(
                self._last_result if self._last_result is not None else self._last_draft
            )
        )
        self.segments_list.itemClicked.connect(self._on_segment_activated)
        self.segments_list.itemActivated.connect(self._on_segment_activated)
        self.suggestions_list.currentRowChanged.connect(self._on_review_row_changed)
        self.suggestions_list.itemClicked.connect(self._on_review_item_clicked)
        self.suggestions_list.itemDoubleClicked.connect(
            self._on_review_item_double_clicked
        )
        self.apply_suggestion_button.clicked.connect(self._on_apply_clicked)
        self.finish_review_button.clicked.connect(self.review_finish_requested.emit)

        self._select_combo(manager.model.key)
        self._update_context_counter()
        self._update_vocabulary_hint()
        self.refresh_model_status()

    # --- stan widoku -------------------------------------------------------

    def refresh_model_status(self) -> None:
        """Aktualizuje opis i status modelu oraz dostępność akcji."""
        model = self._manager.model
        self.info_label.setText(
            tr(
                "asr.model.info",
                model=model.display_name,
                license=model.license_id,
                size=format_size(model.approx_size_bytes),
                ram=format_size(model.min_ram_bytes),
            )
        )
        self.info_label.setToolTip(
            tr(
                "asr.model.info.tooltip",
                url=model.source_url,
                path=self._manager.model_dir,
            )
            + f"\n\n{model.description}"
        )
        ready = self._manager.is_downloaded()
        self._set_model_status(
            tr("asr.model.ready") if ready else tr("asr.model.missing"),
            "success" if ready else "neutral",
        )
        self.download_button.setVisible(not ready)
        self.delete_model_button.setVisible(ready or self._manager.model_dir.is_dir())
        self._refresh_combo_labels()
        self._update_model_actions()
        self._update_transcribe_availability()

    # --- wybór modelu i ustawienia ASR ------------------------------------

    @property
    def manager(self) -> ModelManager:
        """Menedżer wybranego modelu (katalog modeli z ustawień)."""
        return self._manager

    def diarization_ready(self) -> bool:
        """Czy model podziału na mówców jest pobrany."""
        return self._manager.with_model(DIARIZATION_MODEL).is_downloaded()

    @property
    def model(self) -> AsrModelInfo:
        """Model wybrany w panelu."""
        return self._manager.model

    @property
    def model_dir(self) -> Path:
        return self._manager.model_dir

    def select_model(self, key: str) -> None:
        """Wybiera model (np. z ustawień) bez emitowania ``model_changed``."""
        model = model_by_key(key)
        if model == self._manager.model:
            self._select_combo(model.key)
            return
        self._manager = self._manager.with_model(model)
        self._select_combo(model.key)
        self.refresh_model_status()

    def set_asr_settings(self, settings: AsrSettings) -> None:
        """Stosuje ustawienia ASR: model, katalog modeli, urządzenie, słownik."""
        self._device = settings.device
        self._chunked = settings.chunked
        self._word_timestamps = settings.word_timestamps
        self._diarize = settings.diarize
        self._diarize_speakers = settings.diarize_speakers
        self._global_vocabulary = settings.vocabulary_words
        self._update_vocabulary_hint()
        if self.is_downloading() or self.is_transcribing():
            return  # model i katalog zmienią się przy następnych ustawieniach
        manager = self._manager
        if settings.models_root != self._models_root_setting:
            root = Path(settings.models_root) if settings.models_root else None
            manager = manager.with_models_root(root)
            self._models_root_setting = settings.models_root
        model = model_by_key(settings.model_key)
        if model != manager.model:
            manager = manager.with_model(model)
        self._manager = manager
        self._select_combo(manager.model.key)
        self.refresh_model_status()

    def _select_combo(self, key: str) -> None:
        index = self.model_combo.findData(key)
        if index >= 0 and index != self.model_combo.currentIndex():
            self._updating = True
            try:
                self.model_combo.setCurrentIndex(index)
            finally:
                self._updating = False

    def _on_model_combo_changed(self, index: int) -> None:
        if self._updating or index < 0:
            return
        key = str(self.model_combo.itemData(index))
        self.select_model(key)
        self.model_changed.emit(key)

    def _refresh_combo_labels(self) -> None:
        for index in range(self.model_combo.count()):
            model = model_by_key(str(self.model_combo.itemData(index)))
            downloaded = self._manager.with_model(model).is_downloaded()
            self.model_combo.setItemText(
                index,
                tr(
                    "asr.model.item",
                    model=model.display_name.split(" (")[0],
                    size=format_size(model.approx_size_bytes),
                    state=tr(
                        "asr.model.state.ready"
                        if downloaded
                        else "asr.model.state.missing"
                    ),
                ),
            )

    def _update_model_actions(self) -> None:
        busy = self.is_downloading() or self.is_transcribing()
        self.model_combo.setEnabled(not busy)
        self.delete_model_button.setEnabled(not busy)

    # --- usuwanie modelu ---------------------------------------------------

    def _on_delete_clicked(self) -> None:
        """Usuwa pobrany model po potwierdzeniu (ACC-36)."""
        model = self._manager.model
        answer = QMessageBox.question(
            self,
            tr("asr.delete.title"),
            tr(
                "asr.delete.confirm",
                model=model.display_name,
                size=format_size(self._manager.disk_usage()),
                path=self._manager.model_dir,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            freed = self._manager.delete()
        except (OSError, ValueError) as error:
            logger.warning("Model could not be deleted", exc_info=True)
            QMessageBox.warning(
                self, tr("asr.delete.title"), tr("asr.delete.error", reason=error)
            )
            self.refresh_model_status()
            return
        self.refresh_model_status()
        self._set_model_status(
            tr("asr.delete.done", size=format_size(freed)), "neutral"
        )

    # --- kontekst i słownik ------------------------------------------------

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
        podpowiedź — tekst wpisany przez użytkownika zostaje.
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

        Podział na mówców — gdy włączony w ustawieniach i model jest pobrany.
        """
        prompt, vocabulary = self.asr_context()
        diarization = self._manager.with_model(DIARIZATION_MODEL)
        diarize = self._diarize and diarization.is_downloaded()
        return DecodingOptions(
            device=self._device,
            initial_prompt=prompt or None,
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

    def _on_rules_toggled(self, expanded: bool) -> None:
        self.rules_details.setVisible(expanded)
        self.rules_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._update_rules_summary()

    def _update_rules_summary(self) -> None:
        enabled = len(self.selected_rule_codes())
        action = (
            tr("asr.rules.collapse")
            if self.rules_toggle.isChecked()
            else tr("asr.rules.change")
        )
        self.rules_toggle.setText(
            tr(
                "asr.rules.summary",
                enabled=enabled,
                total=len(self.rule_checkboxes),
                action=action,
            )
        )

    def _set_model_status(self, text: str, tone: str) -> None:
        self.model_status_label.setText(text)
        set_props(self.model_status_label, tone=tone)

    def set_audio_available(self, available: bool) -> None:
        """Informuje panel o zmianie nagrania (nowe nagranie albo brak).

        Lista segmentów jest czyszczona: segmenty poprzedniego nagrania nie
        mogą przewijać nowego pliku (ACC-20).
        """
        self._audio_available = available
        self.segments_list.clear()
        self._update_transcribe_availability()

    def set_segment_preroll_ms(self, preroll_ms: int) -> None:
        """Ile przed początkiem segmentu startuje odsłuch (z ustawień)."""
        self._segment_preroll_ms = max(0, preroll_ms)

    def _on_segment_activated(self, item: QListWidgetItem) -> None:
        start_ms = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(start_ms, int):
            self.seek_requested.emit(max(0, start_ms - self._segment_preroll_ms))

    def _update_transcribe_availability(self) -> None:
        available = (
            self._manager.is_downloaded()
            and self._audio_available
            and self._transcribe_thread is None
        )
        self.transcribe_button.setEnabled(available)
        self.fragment_button.setEnabled(available)

    # --- pobieranie ----------------------------------------------------------

    def _on_download_clicked(self) -> None:
        """Żąda pobrania modelu po jawnej zgodzie użytkownika (REQ-10)."""
        answer = QMessageBox.question(
            self,
            tr("asr.download.title"),
            self.download_consent_text(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_download()

    def download_consent_text(self) -> str:
        """Treść pytania o zgodę: nazwa, źródło, licencja, rozmiar, katalog."""
        model = self._manager.model
        return tr(
            "asr.download.consent",
            model=model.display_name,
            url=model.source_url,
            license=model.license_id,
            size=format_size(model.approx_size_bytes),
            path=self._manager.model_dir,
        )

    def _start_download(self) -> None:
        self.download_button.setEnabled(False)
        self.download_progress.setRange(0, 0)
        self.download_progress.setVisible(True)
        self.cancel_download_button.setVisible(True)
        self._set_model_status(tr("asr.download.progress"), "accent")
        logger.info("Model download started: %s", self._manager.model.key)
        thread = DownloadThread(self._manager, self)
        self._download_thread = thread
        self._update_model_actions()
        thread.progressed.connect(self._on_download_progress)
        thread.succeeded.connect(self._on_download_succeeded)
        thread.failed.connect(self._on_download_failed)
        thread.cancelled.connect(self._on_download_cancelled)
        thread.start()

    def _on_download_progress(self, done: int, total: int | None, name: str) -> None:
        if total:
            self.download_progress.setRange(0, int(total))
            self.download_progress.setValue(int(done))
        percent = f" — {done / total:.0%}" if total else ""
        self._set_model_status(
            tr(
                "asr.download.file",
                name=name,
                done=format_size(done),
                percent=percent,
            ),
            "accent",
        )

    def _on_download_succeeded(self) -> None:
        logger.info("Model download finished: %s", self._manager.model.key)
        self._finish_download()
        self.refresh_model_status()

    def _on_download_failed(self, error: AppError) -> None:
        self._finish_download()
        self._set_model_status(tr("asr.model.missing"), "danger")
        self._show_error(tr("asr.download.error"), error)

    def _on_download_cancelled(self) -> None:
        logger.info("Model download cancelled")
        self._finish_download()
        self.refresh_model_status()
        self._set_model_status(tr("asr.download.cancelled"), "neutral")

    def _finish_download(self) -> None:
        thread = self._download_thread
        self._download_thread = None
        if thread is not None:
            if not thread.isFinished():
                thread.wait(5000)
            thread.deleteLater()
        self.download_progress.setVisible(False)
        self.cancel_download_button.setVisible(False)
        self.cancel_download_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self._update_model_actions()

    def _on_cancel_download(self) -> None:
        if self._download_thread is not None:
            self._download_thread.cancel()
            self.cancel_download_button.setEnabled(False)

    def is_downloading(self) -> bool:
        return self._download_thread is not None

    def cancel_download_and_wait(self, timeout_ms: int) -> bool:
        """Przerywa pobieranie i czeka na wątek (zamknięcie okna, BUG-01).

        Zwraca True, gdy wątek się zakończył — można bezpiecznie zniszczyć
        panel. Katalog częściowy usuwa sam wątek przed zakończeniem.
        """
        thread = self._download_thread
        if thread is None:
            return True
        self._on_cancel_download()
        if not thread.wait(timeout_ms):
            return False
        self._finish_download()
        return True

    # --- transkrypcja --------------------------------------------------------

    def _on_transcribe_clicked(self) -> None:
        self._start_transcription(None)

    def _on_fragment_clicked(self) -> None:
        """Transkrypcja fragmentu A–B (propozycja 10A)."""
        clip = self._clip_provider()
        if clip is None:
            self.transcribe_status_label.setText(tr("asr.fragment.no_range"))
            return
        start_ms, end_ms = clip
        self._start_transcription((start_ms / 1000, end_ms / 1000))

    def _start_transcription(self, clip: tuple[float, float] | None) -> None:
        audio_path = self._audio_path_provider()
        if audio_path is None:
            self.transcribe_status_label.setText(tr("asr.no_audio"))
            return
        if not self._confirm_memory():
            return
        self._clip_mode = clip is not None
        self.transcribe_button.setEnabled(False)
        self.fragment_button.setEnabled(False)
        self.cancel_transcribe_button.setVisible(True)
        self.transcribe_status_label.setText(tr("asr.transcribing"))
        self.device_label.setText("")
        if not self._clip_mode:
            self.segments_list.clear()
            self.reinsert_draft_button.setEnabled(False)
        options = replace(self.decoding_options(), clip=clip)
        self._diarizing = options.diarizes
        # Bez treści kontekstu i słownika — to dane z wywiadu.
        logger.info(
            "Transcription started: model=%s, audio=%s, device=%s, chunked=%s, "
            "word_timestamps=%s, diarize=%s, speakers=%s, clip=%s, prompt=%s, "
            "hotwords=%s",
            self._manager.model.key,
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
        self._transcribe_started = time.monotonic()
        thread = TranscribeThread(
            audio_path,
            self._manager.model_dir,
            self._transcribe_impl,
            self,
            model=self._manager.model,
            options=options,
        )
        if not self._clip_mode:
            thread.segment_ready.connect(self._on_segment_ready)
        thread.progressed.connect(self._on_transcribe_progress)
        thread.succeeded.connect(self._on_transcribe_succeeded)
        thread.failed.connect(self._on_transcribe_failed)
        thread.cancelled.connect(self._on_transcribe_cancelled)
        self._transcribe_thread = thread
        self._running_model_key = self._manager.model.key
        self._update_model_actions()
        thread.start()
        self.transcription_started.emit()

    def _confirm_memory(self) -> bool:
        """Ostrzega, gdy model wymaga więcej RAM, niż ma komputer."""
        model = self._manager.model
        memory = total_memory_bytes()
        if memory is None or memory >= model.min_ram_bytes:
            return True
        answer = QMessageBox.question(
            self,
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

    def _on_segment_ready(self, segment: SegmentResult) -> None:
        item = QListWidgetItem(
            f"{format_timestamp(segment.start_s)}–{format_timestamp(segment.end_s)} "
            f"({segment.confidence:.0%}) {segment.text.strip()}"
        )
        item.setData(Qt.ItemDataRole.UserRole, int(segment.start_s * 1000))
        if segment.confidence < LOW_CONFIDENCE:
            item.setForeground(QColor(tokens().warning))
            item.setToolTip(tr("asr.low_confidence.tooltip"))
        self.segments_list.addItem(item)

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
        if self._clip_mode:
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
        self._show_error(tr("asr.failed.title"), error)

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
        self._update_model_actions()
        self._update_transcribe_availability()
        self.transcription_finished.emit()

    @property
    def last_result(self) -> TranscriptionResult | None:
        """Ostatni udany wynik ASR (do zapisu w projekcie)."""
        return self._last_result

    @property
    def last_model_key(self) -> str | None:
        """Klucz modelu, którym obliczono ostatni wynik (None — nieznany)."""
        return self._last_model_key if self._last_result is not None else None

    def restore_result(
        self, result: TranscriptionResult | None, model_key: str | None = None
    ) -> None:
        """Odtwarza wynik ASR z projektu: segmenty i „Wstaw szkic ponownie”.

        Nie emituje ``draft_ready`` — tekst dokumentu pochodzi z projektu.
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
        """Prosi o przerwanie trwającej transkrypcji (np. z nakładki)."""
        self._on_cancel_transcribe()

    def _on_cancel_transcribe(self) -> None:
        if self._transcribe_thread is not None:
            self._transcribe_thread.cancel()
            self.cancel_transcribe_button.setEnabled(False)

    # --- reguły i przegląd ----------------------------------------------------

    def set_rules(self, rules: tuple[RuleInfo, ...]) -> None:
        """Lista reguł z pewnością; zaznaczenie istniejących reguł zostaje.

        Nowa reguła jest zaznaczona według ``auto_apply`` z definicji.
        """
        previous = self.selected_rule_codes()
        known = set(self.rule_checkboxes)
        for checkbox in self.rule_checkboxes.values():
            self._rules_layout.removeWidget(checkbox)
            checkbox.deleteLater()
        self.rule_checkboxes = {}
        for rule in rules:
            checkbox = QCheckBox(_rule_text(rule.label, rule.confidence))
            checkbox.setChecked(
                rule.code in previous if rule.code in known else rule.auto_apply
            )
            checkbox.setToolTip(tr("asr.rule.tooltip"))
            checkbox.toggled.connect(self._update_rules_summary)
            self._rules_layout.addWidget(checkbox)
            self.rule_checkboxes[rule.code] = checkbox
        self._update_rules_summary()

    def selected_rule_codes(self) -> frozenset[str]:
        """Kody reguł zaznaczonych do automatycznego stosowania (REQ-15)."""
        return frozenset(
            code for code, box in self.rule_checkboxes.items() if box.isChecked()
        )

    def set_review_items(self, items: list[tuple[Suggestion, bool]]) -> None:
        """Pokazuje zmiany zastosowane automatycznie i pozostałe propozycje.

        ``items`` to pary (propozycja, czy zastosowana) w kolejności tekstu.
        """
        self._review_applied = [applied for _suggestion, applied in items]
        self.suggestions_list.clear()
        if not items:
            item = QListWidgetItem(tr("asr.review.empty"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.suggestions_list.addItem(item)
        for suggestion, applied in items:
            item = QListWidgetItem(_review_label(suggestion, applied))
            item.setToolTip(suggestion.message)
            if applied:
                item.setForeground(QColor(tokens().success))
            self.suggestions_list.addItem(item)
        self.finish_review_button.setEnabled(bool(items))
        self._on_review_row_changed(self.suggestions_list.currentRow())

    def clear_review(self) -> None:
        self._review_applied = []
        self.suggestions_list.clear()
        self.finish_review_button.setEnabled(False)
        self.apply_suggestion_button.setEnabled(False)

    def _on_review_row_changed(self, row: int) -> None:
        self.apply_suggestion_button.setEnabled(
            0 <= row < len(self._review_applied) and not self._review_applied[row]
        )

    def _on_review_item_clicked(self, item: QListWidgetItem) -> None:
        index = self.suggestions_list.row(item)
        if 0 <= index < len(self._review_applied):
            self.review_item_activated.emit(index)

    def _on_review_item_double_clicked(self, item: QListWidgetItem) -> None:
        index = self.suggestions_list.row(item)
        if 0 <= index < len(self._review_applied) and not self._review_applied[index]:
            self.review_item_apply_requested.emit(index)

    def _on_apply_clicked(self) -> None:
        index = self.suggestions_list.currentRow()
        if 0 <= index < len(self._review_applied) and not self._review_applied[index]:
            self.review_item_apply_requested.emit(index)

    # --- błędy ---------------------------------------------------------------

    def _show_error(self, title: str, error: AppError) -> None:
        """NFR-03: zrozumiały komunikat z możliwością ponowienia działania."""
        log_user_error(error, stacklevel=2)
        message = error.user_message
        if error.retry_hint:
            message += f"\n\n{error.retry_hint}"
        QMessageBox.warning(self, title, message)


class _AutoHideLabel(QLabel):
    """Etykieta ukryta, gdy nie ma treści — pusta nie zostawia dziury."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:  # noqa: N802 — API Qt
        super().setText(text)
        self.setVisible(bool(text))


def _rule_text(label: str, confidence: float) -> str:
    """Dwie linie: reguła, potem przykład i pewność — mieszczą się w panelu."""
    rule, has_example, example = label.partition(" (")
    detail = f"{example.removesuffix(')')} · " if has_example else ""
    return f"{rule}\n{detail}{tr('asr.confidence', confidence=f'{confidence:.0%}')}"


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    set_props(label, role="section")
    return label


def _divider() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    set_props(line, role="divider")
    return line


def _step(number: str, title: str, items: list) -> QWidget:
    """Krok panelu: numer w kółku, tytuł i treść wcięta pod tytułem."""
    badge = QLabel(number)
    set_props(badge, role="step")
    header = QHBoxLayout()
    header.setSpacing(10)
    header.addWidget(badge)
    header.addWidget(_section_label(title), stretch=1)
    body = QVBoxLayout()
    body.setContentsMargins(32, 0, 0, 0)
    body.setSpacing(8)
    for item in items:
        if isinstance(item, QWidget):
            body.addWidget(item)
        else:
            body.addLayout(item)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addLayout(header)
    layout.addLayout(body)
    return widget


def _review_label(suggestion: Suggestion, applied: bool) -> str:
    """Np. „✓ robią → robioᵐ (Nosowość, 50%)” — słowo przed i po zmianie."""
    replacement = list(suggestion.replacement)
    for start, end in suggestion.superscript_ranges:
        for i in range(start, end):
            replacement[i] = replacement[i].translate(_SUPERSCRIPT_LETTERS)
    before = suggestion.word or suggestion.original
    offset = suggestion.start - suggestion.word_start if suggestion.word else 0
    after = (
        before[:offset]
        + "".join(replacement)
        + before[offset + len(suggestion.original) :]
    )
    mark = APPLIED_MARK if applied else PENDING_MARK
    category = suggestion.message.split(":")[0]
    return f"{mark} {before} → {after} ({category}, {suggestion.confidence:.0%})"


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
