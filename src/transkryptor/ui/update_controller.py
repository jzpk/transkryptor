"""Aktualizacje w oknie głównym: wątek tła i baner w pasku stanu.

Logika (limit zapytań, API, pobieranie, instalacja) jest w pakiecie
``transkryptor.update`` bez Qt; ten moduł tylko ją uruchamia i prezentuje.

- Sprawdzenie odbywa się przy starcie, na ekranie startowym
  (``ui/startup_screen.py``), który pokazuje etap i postęp pobierania.
  Wątek ekranu przejmuje potem :meth:`UpdateController.adopt` - także gdy
  użytkownik pominął ekran, a pobieranie trwa dalej w tle.
- Wynik jest cichy: brak sieci, błąd albo wyczerpany limit trafiają tylko do
  dziennika. Gotowa aktualizacja pokazuje baner z przyciskiem
  „Uruchom ponownie i zaktualizuj”, a nowsza wersja bez samoaktualizacji -
  sam komunikat w pasku stanu.
- Instalacja zamyka okno zwykłą drogą (``close``), więc obowiązuje ochrona
  przed utratą niewyeksportowanej pracy (ACC-10).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QWidget,
)

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props
from transkryptor.update.install import apply_update
from transkryptor.update.releases import is_newer
from transkryptor.update.service import UpdateOutcome, UpdateService, UpdateStatus

logger = logging.getLogger(__name__)

# Zamykanie aplikacji czeka na wątek co najwyżej tyle (limit połączenia to 10 s).
SHUTDOWN_WAIT_MS = 15_000


class UpdateThread(QThread):
    """Jeden przebieg ``UpdateService.run`` w tle z kooperacyjnym anulowaniem.

    ``outcome`` zostaje po zakończeniu - odbiorca podłączony później (okno
    tworzone w trakcie sprawdzania) odczyta wynik bez sygnału.
    """

    finished_with = Signal(object)  # UpdateOutcome
    stage_changed = Signal(object, object)  # UpdateStage, ReleaseInfo | None
    progressed = Signal(object, object)  # pobrane bajty, całość | None

    def __init__(self, service: UpdateService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._cancel_requested = False
        self.outcome: UpdateOutcome | None = None

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            outcome = self._service.run(
                lambda: self._cancel_requested,
                on_progress=lambda done, total: self.progressed.emit(done, total),
                on_stage=lambda stage, release: self.stage_changed.emit(stage, release),
            )
        except Exception as error:  # noqa: BLE001 - wątek nie może przepaść
            logger.exception("Update check crashed")
            outcome = UpdateOutcome(
                UpdateStatus.ERROR,
                error=UpdateError(user_message=tr("update.error.check", reason=error)),
            )
        self.outcome = outcome
        self.finished_with.emit(outcome)


class UpdateController(QObject):
    """Wynik sprawdzenia przy starcie i instalacja nowej wersji z poziomu okna."""

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

        self.banner = QWidget()
        layout = QHBoxLayout(self.banner)
        layout.setContentsMargins(0, 0, 0, 0)
        self.banner_label = QLabel()
        self.banner_label.setTextFormat(Qt.TextFormat.PlainText)
        set_props(self.banner_label, role="status", tone="accent")
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

    def create_thread(self) -> UpdateThread:
        """Nowy (nieuruchomiony) przebieg sprawdzenia, np. dla ekranu startowego."""
        return UpdateThread(self._service_factory())

    def start_automatic(self) -> None:
        """Sprawdzenie w tle bez ekranu startowego i bez komunikatów."""
        if self.is_running:
            return
        thread = self.create_thread()
        self.adopt(thread)
        thread.start()

    def adopt(self, thread: UpdateThread) -> None:
        """Przejmuje przebieg uruchomiony gdzie indziej (ekran startowy).

        Wynik zakończonego przebiegu jest stosowany od razu; trwający
        przebieg kończy się w tle i wtedy pokazuje baner.
        """
        if self.is_running:
            return
        thread.setParent(self)
        self._thread = thread
        thread.finished_with.connect(self._on_thread_finished)
        if thread.outcome is not None:
            self._on_thread_finished(thread.outcome)

    def _on_thread_finished(self, outcome: UpdateOutcome) -> None:
        # Wynik bywa odczytany z wątku, zanim dotrze jego sygnał - raz.
        if self._thread is None:
            return
        self._on_finished(outcome)

    def _on_finished(self, outcome: UpdateOutcome) -> None:
        self._release_thread()
        release = outcome.release
        status = outcome.status
        logger.info(
            "Update check finished: %s (latest release %s)",
            status.name,
            release.version if release else "unknown",
        )
        if outcome.error is not None:
            logger.warning(
                "Update check error: %s",
                type(outcome.error).__name__,
                exc_info=outcome.error,
            )

        if status is UpdateStatus.READY and outcome.artifact is not None:
            self._show_ready(release.version if release else "", outcome.artifact)
        elif release is not None and is_newer(release.version, __version__):
            # Nowsza wersja bez gotowego pliku (tryb deweloperski albo błąd
            # pobierania): tylko informacja, bez odnośnika do pobrania.
            self._show_available(release.version)

    def _show_ready(self, version: str, artifact: Path) -> None:
        self._artifact = artifact
        self.banner_label.setText(tr("update.ready", version=version))
        self.install_button.setVisible(True)
        self.banner.setVisible(True)

    def _show_available(self, version: str) -> None:
        if self._artifact is not None:
            return
        self.banner_label.setText(tr("update.available", version=version))
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
