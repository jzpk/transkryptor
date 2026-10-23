"""Podział na mówców w zakładce ASR ustawień: opcja i model do pobrania.

Opcja działa tylko z pobranym modelem diaryzacji (``asr.models.DIARIZATION_MODEL``).
Pobranie wymaga jawnej zgody — bez modelu pole wyboru jest wyłączone, a
zapamiętany wybór użytkownika zostaje bez zmian. Po pobraniu opcja jest
włączona (domyślnie). Pobieranie biegnie w tle (``DownloadThread``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.asr.manager import ModelManager
from transkryptor.asr.models import DIARIZATION_MODEL, format_size
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.asr_panel import DownloadThread
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props

logger = logging.getLogger(__name__)


class DiarizationBox(QWidget):
    """Pole „Podział na mówców” ze stanem, pobraniem i usunięciem modelu."""

    def __init__(self, manager: ModelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager.with_model(DIARIZATION_MODEL)
        self._wanted = True
        self._thread: DownloadThread | None = None

        self.check = QCheckBox(tr("settings.asr.diarize"))
        self.check.setToolTip(tr("settings.asr.diarize.tooltip"))
        self.check.toggled.connect(self._on_toggled)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        set_props(self.status_label, role="muted")
        self.download_button = QPushButton(tr("settings.asr.diarize.download"))
        self.download_button.clicked.connect(self._on_download_clicked)
        self.delete_button = QPushButton(tr("asr.delete"))
        self.delete_button.clicked.connect(self._on_delete_clicked)
        self.cancel_button = QPushButton(tr("asr.download.cancel"))
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.download_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.check)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)
        self.refresh()

    @property
    def manager(self) -> ModelManager:
        return self._manager

    def is_available(self) -> bool:
        return self._manager.is_downloaded()

    def value(self) -> bool:
        """Wybór użytkownika do zapisu (także gdy modelu nie ma)."""
        return self._wanted

    def set_value(self, wanted: bool) -> None:
        self._wanted = wanted
        self.refresh()

    def set_models_root(self, models_root: Path | None) -> None:
        """Katalog modeli zmieniony w ustawieniach — stan modelu od nowa."""
        if self._thread is not None:
            return
        self._manager = self._manager.with_models_root(models_root)
        self.refresh()

    def refresh(self) -> None:
        downloading = self._thread is not None
        ready = self.is_available()
        self.check.blockSignals(True)
        self.check.setChecked(ready and self._wanted)
        self.check.blockSignals(False)
        self.check.setEnabled(ready and not downloading)
        self.download_button.setVisible(not ready and not downloading)
        self.delete_button.setVisible(ready and not downloading)
        self.cancel_button.setVisible(downloading)
        self.progress.setVisible(downloading)
        if downloading:
            return
        model = self._manager.model
        size = format_size(model.approx_size_bytes)
        self.status_label.setText(
            tr("settings.asr.diarize.ready", size=size)
            if ready
            else tr("settings.asr.diarize.missing", size=size)
        )

    def _on_toggled(self, checked: bool) -> None:
        if self.is_available():
            self._wanted = checked

    # --- pobieranie ------------------------------------------------------

    def consent_text(self) -> str:
        model = self._manager.model
        return tr(
            "settings.asr.diarize.consent",
            model=model.display_name,
            url=model.source_url,
            license=model.license_id,
            size=format_size(model.approx_size_bytes),
            path=self._manager.model_dir,
        )

    def _on_download_clicked(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("settings.asr.diarize.title"),
            self.consent_text(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_download()

    def start_download(self) -> None:
        if self._thread is not None:
            return
        logger.info("Model download started: %s", self._manager.model.key)
        thread = DownloadThread(self._manager, self)
        self._thread = thread
        self.progress.setRange(0, 0)
        self.status_label.setText(tr("asr.download.progress"))
        thread.progressed.connect(self._on_progress)
        thread.succeeded.connect(self._on_succeeded)
        thread.failed.connect(self._on_failed)
        thread.cancelled.connect(self._on_cancelled)
        self.refresh()
        thread.start()

    def _on_progress(self, done: int, total: int | None, name: str) -> None:
        if total:
            self.progress.setRange(0, int(total))
            self.progress.setValue(int(done))
        percent = f" — {done / total:.0%}" if total else ""
        self.status_label.setText(
            tr("asr.download.file", name=name, done=format_size(done), percent=percent)
        )

    def _on_succeeded(self) -> None:
        logger.info("Model download finished: %s", self._manager.model.key)
        self._finish()
        # Opcja jest domyślnie włączona — działa od razu po pobraniu.
        self._wanted = True
        self.refresh()

    def _on_failed(self, error: AppError) -> None:
        self._finish()
        self.refresh()
        show_error(self, tr("asr.download.error"), error)

    def _on_cancelled(self) -> None:
        logger.info("Model download cancelled")
        self._finish()
        self.refresh()
        self.status_label.setText(tr("asr.download.cancelled"))

    def _on_cancel_clicked(self) -> None:
        if self._thread is not None:
            self._thread.cancel()
            self.cancel_button.setEnabled(False)

    def _finish(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            if not thread.isFinished():
                thread.wait(5000)
            thread.deleteLater()
        self.cancel_button.setEnabled(True)

    def is_downloading(self) -> bool:
        return self._thread is not None

    def cancel_and_wait(self, timeout_ms: int = 10_000) -> None:
        """Przerywa pobieranie przy zamykaniu ustawień."""
        thread = self._thread
        if thread is None:
            return
        thread.cancel()
        thread.wait(timeout_ms)
        self._finish()

    # --- usuwanie --------------------------------------------------------

    def _on_delete_clicked(self) -> None:
        model = self._manager.model
        answer = QMessageBox.question(
            self,
            tr("settings.asr.diarize.title"),
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
            self._manager.delete()
        except (OSError, ValueError) as error:
            logger.warning("Model could not be deleted", exc_info=True)
            QMessageBox.warning(
                self,
                tr("settings.asr.diarize.title"),
                tr("asr.delete.error", reason=error),
            )
        self.refresh()
