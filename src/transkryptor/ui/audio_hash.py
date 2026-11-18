"""Suma SHA-256 nagrania liczona w tle (PERF-03).

Nagranie terenowe ma setki MB, więc skrót liczony w wątku UI zamrażał okno
na sekundy przy imporcie nagrania i otwieraniu projektu. ``HashThread``
liczy go w tle, a :func:`wait_for` czeka na wynik tam, gdzie jest
potrzebny od razu (zapis projektu, sprawdzenie nagrania przy otwieraniu),
nie blokując odświeżania okna. ``AudioHashing`` trzyma bieżące nagranie
sesji (``AudioRef``) i wpisuje do niego sumę, gdy wątek ją policzy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Qt, QThread
from PySide6.QtWidgets import QProgressDialog, QWidget

from transkryptor.document.project import AudioRef
from transkryptor.fileio import file_sha256
from transkryptor.i18n import tr

# (ścieżka, should_cancel) → suma szesnastkowa; przerwanie → InterruptedError.
HashFunction = Callable[..., str]

# Krótkie liczenie kończy się bez migania okna postępu.
PROGRESS_DELAY_MS = 400
WAIT_STEP_MS = 30


class HashThread(QThread):
    """Liczy SHA-256 pliku; ``digest`` to wynik albo None (błąd, przerwanie)."""

    def __init__(
        self,
        path: Path,
        hash_impl: HashFunction = file_sha256,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.digest: str | None = None
        self._hash_impl = hash_impl

    def run(self) -> None:
        try:
            self.digest = self._hash_impl(
                self.path, should_cancel=self.isInterruptionRequested
            )
        except (OSError, InterruptedError):
            self.digest = None


def wait_for(thread: QThread, parent: QWidget, label: str) -> None:
    """Czeka na koniec wątku, obsługując zdarzenia (okno się odświeża).

    Gdy liczenie trwa dłużej niż ``PROGRESS_DELAY_MS``, pokazuje okno
    postępu bez przycisku anulowania.
    """
    if thread.wait(WAIT_STEP_MS):
        return
    dialog = QProgressDialog(label, "", 0, 0, parent)
    dialog.setCancelButton(None)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumDuration(PROGRESS_DELAY_MS)
    try:
        while not thread.wait(WAIT_STEP_MS):
            QCoreApplication.processEvents(
                QEventLoop.ProcessEventsFlag.AllEvents, WAIT_STEP_MS
            )
    finally:
        dialog.close()
        dialog.deleteLater()


class AudioHashing(QObject):
    """Bieżące nagranie sesji i jego suma SHA-256 liczona w tle.

    ``hash_impl`` podstawiają testy (wolna albo licząca wywołania imitacja).
    """

    def __init__(self, dialog_parent: QWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dialog_parent = dialog_parent
        self.hash_impl: HashFunction = file_sha256
        self._audio: AudioRef | None = None
        self._thread: HashThread | None = None
        self._threads: set[HashThread] = set()

    @property
    def audio(self) -> AudioRef | None:
        """Bieżące nagranie (pusta suma - jeszcze liczona albo błąd)."""
        return self._audio

    def running(self) -> tuple[HashThread, ...]:
        """Wątki, które jeszcze liczą (także porzucone, kończące się)."""
        return tuple(self._threads)

    def set(self, path: Path | None, sha256: str | None = None) -> None:
        """Bieżące nagranie; nieznana suma jest liczona w tle (PERF-03)."""
        self.cancel()
        if path is None:
            self._audio = None
            return
        absolute = path.resolve()
        self._audio = AudioRef(absolute_path=str(absolute), sha256=sha256 or "")
        if sha256 is None:
            self._thread = self._start(absolute)

    def wait(self) -> None:
        """Czeka na sumę bieżącego nagrania (zapis projektu, paczki)."""
        thread = self._thread
        if thread is None:
            return
        wait_for(thread, self._dialog_parent, tr("session.audio_hash.progress"))
        self._apply(thread)

    def hash_now(self, path: Path) -> str | None:
        """Suma pliku od razu potrzebna (okno odświeża się w trakcie)."""
        thread = self._start(path)
        wait_for(thread, self._dialog_parent, tr("session.audio_hash.progress"))
        return thread.digest

    def cancel(self) -> None:
        """Porzuca liczenie dla poprzedniego nagrania (wynik zostanie pominięty)."""
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.requestInterruption()

    def stop(self) -> None:
        """Przerywa wszystkie wątki sumy i czeka na nie (zamknięcie okna)."""
        self.cancel()
        for thread in list(self._threads):
            thread.requestInterruption()
            thread.wait()

    def _start(self, path: Path) -> HashThread:
        # Bez rodzica Qt: wątek żyje, dopóki trzyma go ``_threads`` albo
        # czekający ``wait_for`` (deleteLater usuwałby go w trakcie czekania).
        thread = HashThread(path, self.hash_impl)
        self._threads.add(thread)
        # Metoda QObject (nie lambda): slot wykona się w wątku UI.
        thread.finished.connect(self._on_finished)
        thread.start()
        return thread

    def _on_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, HashThread):
            return
        thread.wait()  # ``finished`` pada tuż przed końcem wątku
        self._threads.discard(thread)
        if self._thread is thread:
            self._apply(thread)
            self._thread = None

    def _apply(self, thread: HashThread) -> None:
        """Wpisuje sumę, gdy wątek dotyczy bieżącego nagrania."""
        audio = self._audio
        if (
            thread.digest
            and audio is not None
            and not audio.sha256
            and audio.absolute_path == str(thread.path)
        ):
            self._audio = replace(audio, sha256=thread.digest)
