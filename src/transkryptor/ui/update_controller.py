"""Aktualizacje w oknie głównym: wątek tła i baner w pasku stanu.

Logika (sprawdzenie wersji, pobieranie, instalacja) jest w pakiecie
``transkryptor.update`` bez Qt; ten moduł tylko ją uruchamia i prezentuje.

- Sprawdzenie odbywa się przy starcie, na ekranie startowym
  (``ui/startup_screen.py``), który pokazuje etap i postęp pobierania.
  Wątek ekranu przejmuje potem :meth:`UpdateController.adopt` - także gdy
  użytkownik pominął ekran, a pobieranie trwa dalej w tle.
- Potem, dopóki program jest otwarty, sprawdzenie powtarza się po cichu
  co ``CHECK_INTERVAL_S`` (6 godzin) - kto nie zamyka programu przez kilka
  dni, też dostanie nowe wydanie. Odstęp liczy zegar ścienny, sprawdzany
  co ``CHECK_TICK_MS``: czas uśpienia komputera też się liczy, a po
  wybudzeniu zaległe sprawdzenie rusza w ciągu kilku minut. Po pobraniu
  gotowej aktualizacji kolejne sprawdzenia nie są potrzebne.
- Wynik jest cichy: brak sieci albo błąd trafiają tylko do
  dziennika. Gotowa aktualizacja pokazuje baner z przyciskiem
  „Uruchom ponownie i zaktualizuj”, a nowsza wersja bez samoaktualizacji -
  sam komunikat w pasku stanu.
- Ostrzeżenie o luce w bieżącej wersji (podpisane ``advisory.json``,
  ``update/advisory.py``) pokazuje okno (``ui/update_advisory.py``) raz na
  sesję dla danego numeru ostrzeżenia - z propozycją instalacji, gdy nowa
  wersja jest już pobrana. Napis banera dostaje wtedy ton ostrzeżenia.
- Instalacja zamyka okno zwykłą drogą (``close``), więc obowiązuje ochrona
  przed utratą niewyeksportowanej pracy (ACC-10).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
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
from transkryptor.ui.update_advisory import warn_about_advisory
from transkryptor.update.advisory import Advisory
from transkryptor.update.install import apply_update
from transkryptor.update.releases import is_newer
from transkryptor.update.service import UpdateOutcome, UpdateService, UpdateStatus

logger = logging.getLogger(__name__)

# Zamykanie aplikacji czeka na wątek co najwyżej tyle (limit połączenia to 10 s).
SHUTDOWN_WAIT_MS = 15_000
# Ciche sprawdzenie w trakcie pracy: co 6 godzin, zegar ścienny odczytywany
# co 10 minut (QTimer nie liczy czasu uśpienia systemu).
CHECK_INTERVAL_S = 6 * 60 * 60
CHECK_TICK_MS = 10 * 60 * 1000


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
        except Exception as error:  # wątek nie może przepaść
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
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._service_factory = service_factory
        self._apply = apply
        self._clock = clock
        self._thread: UpdateThread | None = None
        self._artifact: Path | None = None
        self._last_check: float | None = None
        self._warned_sequence: int | None = None

        self._build_banner(window)
        self._periodic = QTimer(self)
        self._periodic.setInterval(CHECK_TICK_MS)
        self._periodic.timeout.connect(self.check_if_due)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def _build_banner(self, window: QMainWindow) -> None:
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

    @property
    def periodic_checks_active(self) -> bool:
        return self._periodic.isActive()

    def check_if_due(self) -> None:
        """Ciche sprawdzenie, gdy od poprzedniego minęło ``CHECK_INTERVAL_S``."""
        if self._artifact is not None:
            # Aktualizacja już czeka na instalację - nowe pobranie usunęłoby
            # plik, na który wskazuje baner.
            self._periodic.stop()
            return
        last = self._last_check
        if last is None or self._clock() - last >= CHECK_INTERVAL_S:
            self.start_automatic()

    def adopt(self, thread: UpdateThread) -> None:
        """Przejmuje przebieg uruchomiony gdzie indziej (ekran startowy).

        Wynik zakończonego przebiegu jest stosowany od razu; trwający
        przebieg kończy się w tle i wtedy pokazuje baner. Od pierwszego
        przebiegu działa też okresowe sprawdzanie (``check_if_due``).
        """
        if self.is_running:
            return
        self._last_check = self._clock()
        if self._artifact is None and not self._periodic.isActive():
            self._periodic.start()
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
        if outcome.advisory is not None:
            self._warn(outcome.advisory)

    def _warn(self, advisory: Advisory) -> None:
        set_props(self.banner_label, tone="warning")
        if self._warned_sequence == advisory.sequence:
            return
        self._warned_sequence = advisory.sequence
        # Po bieżącym zdarzeniu: przy starcie okno jest wtedy już widoczne.
        QTimer.singleShot(0, lambda: self._show_advisory(advisory))

    def _show_advisory(self, advisory: Advisory) -> None:
        if warn_about_advisory(
            self._window, advisory, can_install=self._artifact is not None
        ):
            self.install_now()

    def _show_ready(self, version: str, artifact: Path) -> None:
        self._artifact = artifact
        self._periodic.stop()
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
        self._periodic.stop()
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
