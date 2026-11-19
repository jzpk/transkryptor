"""Baner aktualizacji w pasku stanu okna głównego.

Stany banera (ustawia je ``ui/update_controller.py``):

- oferta: „Dostępna jest nowa wersja X” z przyciskiem „Pobierz i zainstaluj”
  (bez przycisku, gdy ta instalacja nie obsługuje samoaktualizacji);
- pobieranie: napis z wersją i pasek postępu;
- gotowa aktualizacja: „Pobrano nową wersję X” z przyciskiem
  „Uruchom ponownie i zaktualizuj”.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from transkryptor.asr.models import format_size
from transkryptor.i18n import tr
from transkryptor.ui.theme import set_props


class UpdateBanner(QWidget):
    """Napis, pasek postępu i przyciski pobrania albo instalacji."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("update_banner")
        self._build_layout()
        self.setVisible(False)

    def _build_layout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        set_props(self.label, role="status", tone="accent")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(140)
        self.detail_label = QLabel()
        set_props(self.detail_label, role="muted")
        self.download_button = QPushButton(tr("update.download"))
        self.download_button.setObjectName("update_download_button")
        self.download_button.setToolTip(tr("update.download.tooltip"))
        set_props(self.download_button, variant="primary")
        self.install_button = QPushButton(tr("update.install"))
        set_props(self.install_button, variant="primary")
        for widget in (
            self.label,
            self.progress,
            self.detail_label,
            self.download_button,
            self.install_button,
        ):
            layout.addWidget(widget)

    def _show(self, text: str, *, downloading: bool = False) -> None:
        self.label.setText(text)
        self.progress.setVisible(downloading)
        self.detail_label.setVisible(downloading)
        self.download_button.setVisible(False)
        self.install_button.setVisible(False)
        self.setVisible(True)

    def show_offer(self, version: str, *, can_download: bool) -> None:
        self._show(tr("update.available", version=version))
        self.download_button.setVisible(can_download)

    def show_downloading(self, version: str) -> None:
        self._show(tr("update.downloading", version=version), downloading=True)
        self.progress.setRange(0, 0)
        self.detail_label.clear()

    def set_progress(self, done: int, total: int | None) -> None:
        if total:
            # QProgressBar ma zakres int - liczymy w kilobajtach.
            self.progress.setRange(0, max(1, total // 1024))
            self.progress.setValue(min(done, total) // 1024)
            self.detail_label.setText(
                tr(
                    "update.progress",
                    done=format_size(done),
                    total=format_size(total),
                    percent=int(done * 100 / total),
                )
            )
        else:
            self.progress.setRange(0, 0)
            self.detail_label.setText(format_size(done))

    def show_ready(self, version: str) -> None:
        self._show(tr("update.ready", version=version))
        self.install_button.setVisible(True)
