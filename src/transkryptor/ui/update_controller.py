"""Aktualizacje w oknie głównym: wątki tła i baner w pasku stanu.

Logika (sprawdzenie wersji, pobieranie, instalacja) jest w pakiecie
``transkryptor.update`` bez Qt; ten moduł tylko ją uruchamia i prezentuje.

- Sprawdzenie odbywa się przy starcie, na ekranie startowym
  (``ui/startup_screen.py``). Wątek ekranu przejmuje potem
  :meth:`UpdateController.adopt` - także gdy użytkownik pominął ekran.
- Potem, dopóki program jest otwarty, sprawdzenie powtarza się po cichu
  co ``CHECK_INTERVAL_S`` (6 godzin) - kto nie zamyka programu przez kilka
  dni, też dowie się o nowym wydaniu. Odstęp liczy zegar ścienny, sprawdzany
  co ``CHECK_TICK_MS``: czas uśpienia komputera też się liczy, a po
  wybudzeniu zaległe sprawdzenie rusza w ciągu kilku minut.
- Sprawdzenie niczego nie pobiera i jest ciche: brak sieci albo błąd trafiają
  tylko do dziennika. Nowsza wersja pokazuje baner (``ui/update_banner.py``)
  z przyciskiem „Pobierz i zainstaluj” - o pobraniu decyduje użytkownik.
  Bez samoaktualizacji (tryb deweloperski) baner jest samym komunikatem.
- Po kliknięciu baner pokazuje postęp pobierania, a gotowy plik od razu
  przechodzi do instalacji. Błąd pobierania pokazuje komunikat i przywraca
  ofertę. Instalacja zamyka okno zwykłą drogą (``close``), więc obowiązuje
  ochrona przed utratą niewyeksportowanej pracy (ACC-10); po odmowie baner
  zostaje z przyciskiem „Uruchom ponownie i zaktualizuj”.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.ui.messages import show_error
from transkryptor.ui.update_banner import UpdateBanner
from transkryptor.update.download import DownloadProgress
from transkryptor.update.install import apply_update
from transkryptor.update.releases import ReleaseInfo, is_newer
from transkryptor.update.service import UpdateOutcome, UpdateService, UpdateStatus

logger = logging.getLogger(__name__)

# Zamykanie aplikacji czeka na wątek co najwyżej tyle (limit połączenia to 10 s).
SHUTDOWN_WAIT_MS = 15_000
# Ciche sprawdzenie w trakcie pracy: co 6 godzin, zegar ścienny odczytywany
# co 10 minut (QTimer nie liczy czasu uśpienia systemu).
CHECK_INTERVAL_S = 6 * 60 * 60
CHECK_TICK_MS = 10 * 60 * 1000


# Zadanie wątku: (czy przerwać, postęp pobierania) -> wynik.
UpdateJob = Callable[[Callable[[], bool], DownloadProgress], UpdateOutcome]


class UpdateThread(QThread):
    """Jedno zadanie serwisu w tle z kooperacyjnym anulowaniem.

    ``outcome`` zostaje po zakończeniu - odbiorca podłączony później (okno
    tworzone w trakcie sprawdzania) odczyta wynik bez sygnału.
    """

    finished_with = Signal(object)  # UpdateOutcome
    progressed = Signal(object, object)  # pobrane bajty, całość | None

    def __init__(self, job: UpdateJob, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._job = job
        self._cancel_requested = False
        self.outcome: UpdateOutcome | None = None

    @classmethod
    def checking(cls, service: UpdateService) -> UpdateThread:
        """Samo sprawdzenie wersji (start, okresowe sprawdzenie)."""
        return cls(lambda _cancel, _progress: service.check())

    @classmethod
    def downloading(cls, service: UpdateService, release: ReleaseInfo) -> UpdateThread:
        """Pobranie wydania na polecenie użytkownika."""
        return cls(lambda cancel, progress: service.download(release, cancel, progress))

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            outcome = self._job(
                lambda: self._cancel_requested,
                lambda done, total: self.progressed.emit(done, total),
            )
        except Exception as error:  # wątek nie może przepaść
            logger.exception("Update task crashed")
            outcome = UpdateOutcome(
                UpdateStatus.ERROR,
                error=UpdateError(user_message=tr("update.error.check", reason=error)),
            )
        self.outcome = outcome
        self.finished_with.emit(outcome)


class UpdateController(QObject):
    """Sprawdzenie w tle, pobranie na życzenie i instalacja nowej wersji."""

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
        self._download: UpdateThread | None = None
        self._offer: ReleaseInfo | None = None
        self._artifact: Path | None = None
        self._ready_version = ""
        self._last_check: float | None = None

        self.banner = UpdateBanner()
        self.banner.download_button.clicked.connect(self.download_now)
        self.banner.install_button.clicked.connect(self.install_now)
        window.statusBar().addPermanentWidget(self.banner)
        self._periodic = QTimer(self)
        self._periodic.setInterval(CHECK_TICK_MS)
        self._periodic.timeout.connect(self.check_if_due)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    @property
    def is_downloading(self) -> bool:
        return self._download is not None

    def create_thread(self) -> UpdateThread:
        """Nowe (nieuruchomione) sprawdzenie, np. dla ekranu startowego."""
        return UpdateThread.checking(self._service_factory())

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
        if self.is_downloading:
            return
        last = self._last_check
        if last is None or self._clock() - last >= CHECK_INTERVAL_S:
            self.start_automatic()

    def adopt(self, thread: UpdateThread) -> None:
        """Przejmuje sprawdzenie uruchomione gdzie indziej (ekran startowy).

        Wynik zakończonego sprawdzenia jest stosowany od razu; trwające
        kończy się w tle i wtedy pokazuje baner. Od pierwszego sprawdzenia
        działa też okresowe sprawdzanie (``check_if_due``).
        """
        if self.is_running:
            return
        self._last_check = self._clock()
        if self._artifact is None and not self._periodic.isActive():
            self._periodic.start()
        thread.setParent(self)
        self._thread = thread
        thread.finished_with.connect(self._on_check_thread_finished)
        if thread.outcome is not None:
            self._on_check_thread_finished(thread.outcome)

    def _on_check_thread_finished(self, outcome: UpdateOutcome) -> None:
        # Wynik bywa odczytany z wątku, zanim dotrze jego sygnał - raz.
        if self._thread is None:
            return
        _dispose(self._thread)
        self._thread = None
        self._log_outcome("Update check", outcome)
        release = outcome.release
        if self._artifact is not None or self.is_downloading or release is None:
            return
        if outcome.status is UpdateStatus.DOWNLOADABLE:
            self._offer = release
            self.banner.show_offer(release.version, can_download=True)
        elif is_newer(release.version, __version__):
            # Nowsza wersja bez samoaktualizacji (tryb deweloperski): tylko
            # informacja, bez odnośnika do pobrania.
            self.banner.show_offer(release.version, can_download=False)

    def download_now(self) -> None:
        """Pobiera oferowaną wersję w tle; gotowy plik od razu instaluje."""
        release = self._offer
        if release is None or self.is_downloading:
            return
        thread = UpdateThread.downloading(self._service_factory(), release)
        thread.setParent(self)
        thread.progressed.connect(self.banner.set_progress)
        thread.finished_with.connect(self._on_download_finished)
        self._download = thread
        self.banner.show_downloading(release.version)
        thread.start()

    def _on_download_finished(self, outcome: UpdateOutcome) -> None:
        if self._download is None:
            return
        _dispose(self._download)
        self._download = None
        self._log_outcome("Update download", outcome)
        status = outcome.status
        if status is UpdateStatus.READY and outcome.artifact is not None:
            self._show_ready(outcome)
            self.install_now()
            return
        if self._offer is not None:
            self.banner.show_offer(self._offer.version, can_download=True)
        if status is UpdateStatus.CANCELLED:
            return
        error = outcome.error or UpdateError(
            user_message=tr("update.error.offline"),
            retry_hint=tr("update.error.later.hint"),
        )
        show_error(self._window, tr("update.title"), error)

    def _show_ready(self, outcome: UpdateOutcome) -> None:
        self._artifact = outcome.artifact
        self._ready_version = outcome.release.version if outcome.release else ""
        self._periodic.stop()
        self.banner.show_ready(self._ready_version)

    def install_now(self) -> None:
        """Zamyka okno (z ochroną pracy) i uruchamia instalację nowej wersji."""
        artifact = self._artifact
        if artifact is None or not self._window.close():
            return
        try:
            self._apply(artifact)
        except UpdateError as error:
            # Plik bywa odrzucony przy ponownej weryfikacji - kolejna próba
            # zaczyna się od pobrania.
            self._artifact = None
            if self._offer is not None:
                self.banner.show_offer(self._offer.version, can_download=True)
            show_error(self._window, tr("update.title"), error)

    def shutdown(self) -> None:
        """Przerywa pobieranie przy zamykaniu aplikacji i czeka na wątki."""
        self._periodic.stop()
        for thread in (self._thread, self._download):
            if thread is not None:
                thread.cancel()
                thread.wait(SHUTDOWN_WAIT_MS)

    @staticmethod
    def _log_outcome(task: str, outcome: UpdateOutcome) -> None:
        release = outcome.release
        logger.info(
            "%s finished: %s (latest release %s)",
            task,
            outcome.status.name,
            release.version if release else "unknown",
        )
        if outcome.error is not None:
            logger.warning(
                "%s error: %s",
                task,
                type(outcome.error).__name__,
                exc_info=outcome.error,
            )


def _dispose(thread: UpdateThread) -> None:
    """Sprząta zakończony wątek."""
    if not thread.isFinished():
        thread.wait(5000)
    thread.deleteLater()
