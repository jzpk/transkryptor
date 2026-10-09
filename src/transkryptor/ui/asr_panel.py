"""Panel lokalnego szkicu ASR: zgoda na pobranie, postęp, reguły, przegląd.

Warstwa UI łączy moduł ``asr`` (bez Qt) z wątkami ``QThread`` i widżetami.
Zgodnie z kontraktem ``asr -> ui`` wątki przekazują wyłącznie stan zadania,
hipotezę, przedziały pewności i błędy — nigdy obiekty GUI.

Panel nie zmienia dokumentu sam: gotowy szkic emituje sygnałem
``draft_ready``, a wstawienie do edytora, automatyczne reguły wybrane
checkboxami (REQ-15) i pojedyncze propozycje (ACC-12) wykonuje główne okno.
Panel pokazuje listę zastosowanych zmian i propozycji do przeglądu (REQ-16).
Kliknięcie segmentu emituje ``seek_requested`` — okno przewija nagranie.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.asr import engine
from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.asr.manager import DownloadCancelled, ModelManager
from transkryptor.asr.models import format_size
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.suggestions import RULES, Suggestion
from transkryptor.ui import icons
from transkryptor.ui.theme import set_props, tokens

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
    ) -> None:
        super().__init__(parent)
        self._audio_path = audio_path
        self._model_dir = model_dir
        self._transcribe_impl = transcribe_impl
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
            )
        except engine.TranscriptionCancelled:
            self.cancelled.emit()
        except AppError as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)


class AsrPanel(QWidget):
    """Panel konfiguracji modelu, pobierania i propozycji transkrypcji."""

    draft_ready = Signal(str)  # tekst szkicu do wstawienia w edytor
    review_item_activated = Signal(int)  # indeks pozycji listy przeglądu
    review_item_apply_requested = Signal(int)
    review_finish_requested = Signal()
    transcription_started = Signal()
    transcription_progress = Signal(float)  # ułamek nagrania 0.0–1.0
    transcription_finished = Signal()
    seek_requested = Signal(int)  # pozycja nagrania w ms

    def __init__(
        self,
        manager: ModelManager,
        audio_path_provider: Callable[[], Path | None] = lambda: None,
        transcribe_impl: Callable[..., TranscriptionResult] = engine.transcribe,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._audio_path_provider = audio_path_provider
        self._transcribe_impl = transcribe_impl
        self._download_thread: DownloadThread | None = None
        self._transcribe_thread: TranscribeThread | None = None
        self._review_applied: list[bool] = []
        self._last_draft = ""
        self._last_result: TranscriptionResult | None = None
        self._audio_available = False
        self._segment_preroll_ms = DEFAULT_SEGMENT_PREROLL_MS

        self.setObjectName("asr_panel")
        model = manager.model
        self.info_label = QLabel(
            tr(
                "asr.model.info",
                model=model.display_name,
                license=model.license_id,
                size=format_size(model.approx_size_bytes),
            )
        )
        self.info_label.setToolTip(
            tr("asr.model.info.tooltip", url=model.source_url, path=manager.model_dir)
        )
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

        self.transcribe_button = QPushButton(tr("asr.transcribe"))
        set_props(self.transcribe_button, variant="primary")
        icons.set_icon(self.transcribe_button, "sparkles", "on_accent", "text_muted")
        self.transcribe_button.setIconSize(icons.ICON_SIZE)
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
        for rule in RULES:
            checkbox = QCheckBox(_rule_text(rule.label, rule.confidence))
            checkbox.setChecked(True)
            checkbox.setToolTip(tr("asr.rule.tooltip"))
            rules_layout.addWidget(checkbox)
            self.rule_checkboxes[rule.code] = checkbox

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
        model_step = _step(
            "1",
            tr("asr.step.model"),
            [
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
        for checkbox in self.rule_checkboxes.values():
            checkbox.toggled.connect(self._update_rules_summary)
        self._update_rules_summary()
        rules_step = _step(
            "2",
            tr("asr.step.rules"),
            [self.rules_toggle, self.rules_details],
        )
        # Krok 3: szkic.
        transcribe_row = QHBoxLayout()
        transcribe_row.addWidget(self.transcribe_button, stretch=1)
        transcribe_row.addWidget(self.cancel_transcribe_button)
        draft_step = _step(
            "3",
            tr("asr.step.draft"),
            [transcribe_row, self.transcribe_status_label, self.reinsert_draft_button],
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

        self.download_button.clicked.connect(self._on_download_clicked)
        self.cancel_download_button.clicked.connect(self._on_cancel_download)
        self.transcribe_button.clicked.connect(self._on_transcribe_clicked)
        self.cancel_transcribe_button.clicked.connect(self._on_cancel_transcribe)
        self.reinsert_draft_button.clicked.connect(
            lambda: self.draft_ready.emit(self._last_draft)
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

        self.refresh_model_status()

    # --- stan widoku -------------------------------------------------------

    def refresh_model_status(self) -> None:
        """Aktualizuje status modelu i dostępność akcji."""
        ready = self._manager.is_downloaded()
        self._set_model_status(
            tr("asr.model.ready") if ready else tr("asr.model.missing"),
            "success" if ready else "neutral",
        )
        self.download_button.setVisible(not ready)
        self._update_transcribe_availability()

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
        self.transcribe_button.setEnabled(
            self._manager.is_downloaded()
            and self._audio_available
            and self._transcribe_thread is None
        )

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
        thread = DownloadThread(self._manager, self)
        thread.progressed.connect(self._on_download_progress)
        thread.succeeded.connect(self._on_download_succeeded)
        thread.failed.connect(self._on_download_failed)
        thread.cancelled.connect(self._on_download_cancelled)
        self._download_thread = thread
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
        self._finish_download()
        self.refresh_model_status()

    def _on_download_failed(self, error: AppError) -> None:
        self._finish_download()
        self._set_model_status(tr("asr.model.missing"), "danger")
        self._show_error(tr("asr.download.error"), error)

    def _on_download_cancelled(self) -> None:
        self._finish_download()
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
        self.download_button.setEnabled(True)

    def _on_cancel_download(self) -> None:
        if self._download_thread is not None:
            self._download_thread.cancel()
            self.cancel_download_button.setEnabled(False)

    # --- transkrypcja --------------------------------------------------------

    def _on_transcribe_clicked(self) -> None:
        audio_path = self._audio_path_provider()
        if audio_path is None:
            self.transcribe_status_label.setText(tr("asr.no_audio"))
            return
        self.transcribe_button.setEnabled(False)
        self.cancel_transcribe_button.setVisible(True)
        self.transcribe_status_label.setText(tr("asr.transcribing"))
        self.segments_list.clear()
        self.reinsert_draft_button.setEnabled(False)
        thread = TranscribeThread(
            audio_path, self._manager.model_dir, self._transcribe_impl, self
        )
        thread.segment_ready.connect(self._on_segment_ready)
        thread.progressed.connect(self._on_transcribe_progress)
        thread.succeeded.connect(self._on_transcribe_succeeded)
        thread.failed.connect(self._on_transcribe_failed)
        thread.cancelled.connect(self._on_transcribe_cancelled)
        self._transcribe_thread = thread
        thread.start()
        self.transcription_started.emit()

    def _on_transcribe_progress(self, fraction: float) -> None:
        self.transcribe_status_label.setText(
            tr("asr.transcribing.percent", percent=int(fraction * 100))
        )
        self.transcription_progress.emit(fraction)

    def _on_segment_ready(self, segment: SegmentResult) -> None:
        item = QListWidgetItem(
            f"{_format_time(segment.start_s)}–{_format_time(segment.end_s)} "
            f"({segment.confidence:.0%}) {segment.text.strip()}"
        )
        item.setData(Qt.ItemDataRole.UserRole, int(segment.start_s * 1000))
        if segment.confidence < LOW_CONFIDENCE:
            item.setForeground(QColor(tokens().warning))
            item.setToolTip(tr("asr.low_confidence.tooltip"))
        self.segments_list.addItem(item)

    def _on_transcribe_succeeded(self, result: TranscriptionResult) -> None:
        self._finish_transcribe()
        self._last_draft = result.text
        self._last_result = result
        if not result.text.strip():
            self.transcribe_status_label.setText(tr("asr.no_speech"))
            return
        self.reinsert_draft_button.setEnabled(True)
        self.transcribe_status_label.setText(tr("asr.draft_ready"))
        self.draft_ready.emit(result.text)

    def _on_transcribe_failed(self, error: AppError) -> None:
        self._finish_transcribe()
        self.transcribe_status_label.setText(tr("asr.failed"))
        self._show_error(tr("asr.failed.title"), error)

    def _on_transcribe_cancelled(self) -> None:
        self._finish_transcribe()
        self.transcribe_status_label.setText(tr("asr.cancelled"))

    def _finish_transcribe(self) -> None:
        thread = self._transcribe_thread
        self._transcribe_thread = None
        if thread is not None:
            if not thread.isFinished():
                thread.wait(5000)
            thread.deleteLater()
        self.cancel_transcribe_button.setVisible(False)
        self.cancel_transcribe_button.setEnabled(True)
        self._update_transcribe_availability()
        self.transcription_finished.emit()

    @property
    def last_result(self) -> TranscriptionResult | None:
        """Ostatni udany wynik ASR (do zapisu w projekcie)."""
        return self._last_result

    def restore_result(self, result: TranscriptionResult | None) -> None:
        """Odtwarza wynik ASR z projektu: segmenty i „Wstaw szkic ponownie”.

        Nie emituje ``draft_ready`` — tekst dokumentu pochodzi z projektu.
        """
        self.segments_list.clear()
        self._last_result = result
        self._last_draft = result.text if result is not None else ""
        if result is not None:
            for segment in result.segments:
                self._on_segment_ready(segment)
        self.reinsert_draft_button.setEnabled(bool(self._last_draft.strip()))
        self.transcribe_status_label.setText(
            tr("asr.restored") if self._last_draft.strip() else ""
        )

    def is_transcribing(self) -> bool:
        return self._transcribe_thread is not None

    def cancel_transcription(self) -> None:
        """Prosi o przerwanie trwającej transkrypcji (np. z nakładki)."""
        self._on_cancel_transcribe()

    def _on_cancel_transcribe(self) -> None:
        if self._transcribe_thread is not None:
            self._transcribe_thread.cancel()
            self.cancel_transcribe_button.setEnabled(False)

    # --- reguły i przegląd ----------------------------------------------------

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


def _format_time(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"
