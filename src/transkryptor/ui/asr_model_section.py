"""Krok „Model” panelu szkicu ASR: wybór, pobieranie za zgodą i usuwanie.

Sekcja trzyma menedżera wybranego modelu (``asr.manager.ModelManager``)
i wątek pobierania. Nie zna transkrypcji: o jej trwaniu dowiaduje się
przez :meth:`ModelSection.set_transcribing`, a o zmianie stanu modelu
informuje sygnałem ``status_changed``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QWidget,
)

from transkryptor.asr.manager import DownloadCancelled, ModelManager
from transkryptor.asr.models import (
    DIARIZATION_MODEL,
    MODELS,
    AsrModelInfo,
    format_size,
    model_by_key,
)
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.settings import AsrSettings
from transkryptor.ui import icons
from transkryptor.ui.asr_widgets import step
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props

logger = logging.getLogger(__name__)


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


class ModelSection(QObject):
    """Wybór modelu z rejestru, pobranie za zgodą i usunięcie (REQ-10)."""

    model_changed = Signal(str)  # klucz modelu wybranego przez użytkownika
    # Zmienił się model, jego katalog albo stan pobrania.
    status_changed = Signal()

    def __init__(self, manager: ModelManager, dialog_parent: QWidget) -> None:
        super().__init__(dialog_parent)
        self._manager = manager
        self._parent = dialog_parent
        self._download_thread: DownloadThread | None = None
        self._transcribing = False
        # Katalog modeli z ostatnio zastosowanych ustawień (None - jeszcze
        # nie stosowano; do tego czasu obowiązuje katalog menedżera).
        self._models_root_setting: str | None = None
        self._updating = False

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

        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        self.delete_model_button.clicked.connect(self._on_delete_clicked)
        self.download_button.clicked.connect(self._on_download_clicked)
        self.cancel_download_button.clicked.connect(self._on_cancel_download)
        self._select_combo(manager.model.key)

    def build_step(self) -> QWidget:
        """Krok 1 panelu: lista modeli, opis, stan i przyciski pobierania."""
        download_row = QHBoxLayout()
        download_row.addWidget(self.download_button)
        download_row.addWidget(self.cancel_download_button)
        download_row.addStretch(1)
        download_row.addWidget(self.delete_model_button)
        return step(
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

    # --- stan ----------------------------------------------------------------

    @property
    def manager(self) -> ModelManager:
        """Menedżer wybranego modelu (katalog modeli z ustawień)."""
        return self._manager

    @property
    def model(self) -> AsrModelInfo:
        return self._manager.model

    @property
    def model_dir(self) -> Path:
        return self._manager.model_dir

    def is_downloaded(self) -> bool:
        return self._manager.is_downloaded()

    def diarization_ready(self) -> bool:
        """Czy model podziału na mówców jest pobrany."""
        return self._manager.with_model(DIARIZATION_MODEL).is_downloaded()

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
        self.status_changed.emit()

    def set_transcribing(self, transcribing: bool) -> None:
        """W trakcie transkrypcji modelu nie można zmienić ani usunąć."""
        self._transcribing = transcribing
        self._update_model_actions()

    # --- wybór modelu i ustawienia -------------------------------------------

    def select_model(self, key: str) -> None:
        """Wybiera model (np. z ustawień) bez emitowania ``model_changed``."""
        model = model_by_key(key)
        if model == self._manager.model:
            self._select_combo(model.key)
            return
        self._manager = self._manager.with_model(model)
        self._select_combo(model.key)
        self.refresh_model_status()

    def apply_settings(self, settings: AsrSettings) -> None:
        """Model i katalog modeli z ustawień; w trakcie pracy - bez zmian."""
        if self.is_downloading() or self._transcribing:
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
        busy = self.is_downloading() or self._transcribing
        self.model_combo.setEnabled(not busy)
        self.delete_model_button.setEnabled(not busy)

    def _set_model_status(self, text: str, tone: str) -> None:
        self.model_status_label.setText(text)
        set_props(self.model_status_label, tone=tone)

    # --- usuwanie modelu -----------------------------------------------------

    def _on_delete_clicked(self) -> None:
        """Usuwa pobrany model po potwierdzeniu (ACC-36)."""
        model = self._manager.model
        answer = QMessageBox.question(
            self._parent,
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
                self._parent,
                tr("asr.delete.title"),
                tr("asr.delete.error", reason=error),
            )
            self.refresh_model_status()
            return
        self.refresh_model_status()
        self._set_model_status(
            tr("asr.delete.done", size=format_size(freed)), "neutral"
        )

    # --- pobieranie ----------------------------------------------------------

    def _on_download_clicked(self) -> None:
        """Żąda pobrania modelu po jawnej zgodzie użytkownika (REQ-10)."""
        answer = QMessageBox.question(
            self._parent,
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
        percent = f" - {done / total:.0%}" if total else ""
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
        show_error(self._parent, tr("asr.download.error"), error)

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

        Zwraca True, gdy wątek się zakończył - można bezpiecznie zniszczyć
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
