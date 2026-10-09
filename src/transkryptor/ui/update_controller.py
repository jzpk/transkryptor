"""Aktualizacje w oknie głównym: wątek tła, baner w pasku stanu, akcja ręczna.

Logika (limit zapytań, API, pobieranie, instalacja) jest w pakiecie
``transkryptor.update`` bez Qt; ten moduł tylko ją uruchamia i prezentuje.

- Sprawdzenie przy starcie jest ciche: brak sieci, błąd albo wyczerpany limit
  nie generują komunikatu. Gotowa aktualizacja pokazuje baner z przyciskiem
  „Uruchom ponownie i zaktualizuj”.
- Akcja „Sprawdź aktualizacje” zawsze odpowiada komunikatem.
- Instalacja zamyka okno zwykłą drogą (``close``), więc obowiązuje ochrona
  przed utratą niewyeksportowanej pracy (ACC-10).
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QWidget,
)

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props
from transkryptor.update.install import apply_update
from transkryptor.update.releases import is_newer, safe_page_url
from transkryptor.update.service import UpdateOutcome, UpdateService, UpdateStatus

# Zamykanie aplikacji czeka na wątek co najwyżej tyle (limit połączenia to 10 s).
SHUTDOWN_WAIT_MS = 15_000


class UpdateThread(QThread):
    """Jeden przebieg ``UpdateService.run`` w tle z kooperacyjnym anulowaniem."""

    finished_with = Signal(object)  # UpdateOutcome

    def __init__(self, service: UpdateService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            outcome = self._service.run(lambda: self._cancel_requested)
        except Exception as error:  # noqa: BLE001 — wątek nie może przepaść
            outcome = UpdateOutcome(
                UpdateStatus.ERROR,
                error=UpdateError(user_message=tr("update.error.check", reason=error)),
            )
        self.finished_with.emit(outcome)


class UpdateController(QObject):
    """Sprawdzanie, pobieranie i instalacja nowej wersji z poziomu okna."""

    def __init__(
        self,
        window: QMainWindow,
        *,
        service_factory: Callable[[], UpdateService] = UpdateService,
        apply: Callable[[Path], None] = apply_update,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._service_factory = service_factory
        self._apply = apply
        self._thread: UpdateThread | None = None
        self._artifact: Path | None = None

        self.check_action = QAction(tr("update.check"), window)
        self.check_action.setToolTip(tr("update.check.tooltip"))
        self.check_action.triggered.connect(lambda _checked=False: self.check_now())

        self.banner = QWidget()
        layout = QHBoxLayout(self.banner)
        layout.setContentsMargins(0, 0, 0, 0)
        self.banner_label = QLabel()
        set_props(self.banner_label, role="status", tone="accent")
        self.banner_label.setOpenExternalLinks(True)
        self.install_button = QPushButton(tr("update.install"))
        set_props(self.install_button, variant="primary")
        self.install_button.clicked.connect(self.install_now)
        layout.addWidget(self.banner_label)
        layout.addWidget(self.install_button)
        self.banner.setVisible(False)
        window.statusBar().addPermanentWidget(self.banner)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start_automatic(self) -> None:
        """Sprawdzenie przy starcie: w tle i bez komunikatów o niepowodzeniu."""
        self._start(manual=False)

    def check_now(self) -> None:
        """Jawne sprawdzenie przez użytkownika (ten sam dzienny limit)."""
        if self.is_running:
            self._window.statusBar().showMessage(tr("update.in_progress"), 5000)
            return
        self._start(manual=True)

    def _start(self, *, manual: bool) -> None:
        if self.is_running:
            return
        thread = UpdateThread(self._service_factory(), self)
        thread.finished_with.connect(
            lambda outcome: self._on_finished(outcome, manual=manual)
        )
        self._thread = thread
        self.check_action.setEnabled(False)
        thread.start()

    def _on_finished(self, outcome: UpdateOutcome, *, manual: bool) -> None:
        self._release_thread()
        self.check_action.setEnabled(True)
        release = outcome.release
        status = outcome.status

        if status is UpdateStatus.READY and outcome.artifact is not None:
            self._show_ready(release.version if release else "", outcome.artifact)
        elif release is not None and is_newer(release.version, __version__):
            # Nowsza wersja bez gotowego pliku (tryb deweloperski albo błąd
            # pobierania): przynajmniej link do strony wydania.
            self._show_available(release.version, release.page_url)

        if not manual:
            return
        if status is UpdateStatus.UP_TO_DATE:
            self._inform(tr("update.up_to_date", version=__version__))
        elif status is UpdateStatus.QUOTA_EXHAUSTED:
            self._inform(tr("update.quota"))
        elif status is UpdateStatus.OFFLINE:
            self._warn(tr("update.offline"))
        elif status is UpdateStatus.ERROR and outcome.error is not None:
            show_error(self._window, tr("update.title"), outcome.error)

    def _show_ready(self, version: str, artifact: Path) -> None:
        self._artifact = artifact
        self.banner_label.setText(tr("update.ready", version=version))
        self.install_button.setVisible(True)
        self.banner.setVisible(True)

    def _show_available(self, version: str, url: str) -> None:
        if self._artifact is not None:
            return
        # Etykieta interpretuje HTML: tylko strona GitHub i escapowanie.
        link = html.escape(safe_page_url(url), quote=True)
        self.banner_label.setText(
            tr("update.available", version=html.escape(version), url=link)
        )
        self.install_button.setVisible(False)
        self.banner.setVisible(True)

    def install_now(self) -> None:
        """Zamyka okno (z ochroną pracy) i uruchamia instalację nowej wersji."""
        artifact = self._artifact
        if artifact is None or not self._window.close():
            return
        try:
            self._apply(artifact)
        except UpdateError as error:
            show_error(self._window, tr("update.title"), error)

    def shutdown(self) -> None:
        """Przerywa pobieranie przy zamykaniu aplikacji i czeka na wątek."""
        thread = self._thread
        if thread is not None:
            thread.cancel()
            thread.wait(SHUTDOWN_WAIT_MS)

    def _release_thread(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            if not thread.isFinished():
                thread.wait(5000)
            thread.deleteLater()

    # Komunikaty jako metody — testy podmieniają je bez okien modalnych.
    def _inform(self, text: str) -> None:
        QMessageBox.information(self._window, tr("update.title"), text)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self._window, tr("update.title"), text)
