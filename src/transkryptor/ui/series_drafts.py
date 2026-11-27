"""Kolejka szkiców ASR dla całej serii nagrań (np. na noc).

„Przygotuj szkice dla serii” bierze nagrania bez szkicu
(``corpus/series_drafts.py``), pyta raz o model i liczbę mówców
(``ui/series_drafts_dialog.py``) i przepisuje je po kolei tym samym
silnikiem co panel ASR. Szkic każdego nagrania trafia do dokumentu tą
samą drogą co szkic z panelu (zapis szkicu, reguły, mówcy) i od razu
zapisuje się w projekcie obok nagrania - przerwanie (także zamknięcie
programu) nie traci gotowych szkiców, a ponowne uruchomienie pomija je.

Na czas kolejki okno jest zablokowane jak przy zwykłej transkrypcji:
nakładka z postępem całej kolejki i szacowanym czasem, blokada uśpienia
systemu (``KeepAwake``, #68) i przycisk anulowania. Błąd jednego nagrania
nie zatrzymuje kolejki - trafia do podsumowania na końcu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from transkryptor.asr.models import MODELS, AsrModelInfo
from transkryptor.asr.results import TranscriptionResult
from transkryptor.audio.probe import duration_ms
from transkryptor.corpus.series import project_for, series_recordings
from transkryptor.corpus.series_drafts import PENDING, draft_queue, draft_state
from transkryptor.document.project import save_project
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.asr_controller import AsrController
from transkryptor.ui.asr_transcribe_thread import TranscribeThread
from transkryptor.ui.series_drafts_dialog import SeriesDraftsDialog, queue_summary
from transkryptor.ui.session import SessionController

# Nagranie o nieznanej długości liczy się w postępie jak minuta.
_UNKNOWN_MS = 60_000


@dataclass
class _Queue:
    """Trwająca kolejka: nagrania do szkicu, postęp i wyniki."""

    recordings: list[Path]
    pending: list[Path]
    durations: list[int]
    model_key: str
    index: int = 0
    done_ms: int = 0
    cancelled: bool = False
    drafted: list[Path] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_ms(self) -> int:
        return sum(self.durations) or 1


class SeriesDrafts(QObject):
    """Kolejka szkiców serii: start, kolejne nagrania, anulowanie, podsumowanie."""

    def __init__(
        self,
        window: QWidget,
        session: SessionController,
        asr: Callable[[], AsrController],
        audio_path: Callable[[], Path | None],
        open_recording: Callable[[Path], bool],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._session = session
        # Późne wiązanie: kontroler ASR powstaje w oknie po kontrolerze serii.
        self._asr_source = asr
        self._audio_path = audio_path
        self._open_recording = open_recording
        self._queue: _Queue | None = None
        self._thread: TranscribeThread | None = None
        # Okna; testy podstawiają gotowe odpowiedzi.
        self.run_dialog: Callable[[SeriesDraftsDialog], int] = lambda d: d.exec()
        self.show_message: Callable[[str, str], None] = self._show_message

    @property
    def busy(self) -> bool:
        return self._queue is not None

    @property
    def _asr(self) -> AsrController:
        return self._asr_source()

    def start(self, folder: Path) -> bool:
        """Pyta o ustawienia i zaczyna kolejkę; False - nic do zrobienia."""
        if self._queue is not None or not self._session.maybe_discard_changes():
            return False
        recordings = series_recordings(folder)
        queue = draft_queue(recordings)
        if not queue.pending:
            self.show_message(tr("series.drafts.title"), tr("series.drafts.nothing"))
            return False
        models = self._downloaded_models()
        if not models:
            self.show_message(tr("series.drafts.title"), tr("series.drafts.no_model"))
            return False
        durations = [duration_ms(path) or _UNKNOWN_MS for path in queue.pending]
        dialog = self._dialog(
            models,
            queue_summary(
                len(queue.pending),
                sum(durations),
                len(queue.drafted),
                len(queue.with_text) + len(queue.unreadable),
            ),
        )
        if self.run_dialog(dialog) != SeriesDraftsDialog.DialogCode.Accepted:
            return False
        self._asr.remember_choice(dialog.model_key, dialog.speakers)
        run = _Queue(recordings, list(queue.pending), durations, dialog.model_key)
        run.skipped.extend(
            (path.name, tr("series.drafts.skip.has_text")) for path in queue.with_text
        )
        run.skipped.extend((path.name, message) for path, message in queue.unreadable)
        self._queue = run
        self._asr.overlay.cancel_requested.connect(self.cancel)
        self._asr.transcription_started()
        QTimer.singleShot(0, self._next)
        return True

    def cancel(self) -> None:
        """Przerywa kolejkę (bieżące nagranie bez szkicu, gotowe zostają)."""
        if self._queue is None:
            return
        self._queue.cancelled = True
        if self._thread is not None:
            self._thread.cancel()

    def wait(self) -> None:
        """Czeka na koniec kolejki (testy)."""
        while self._queue is not None:
            QApplication.processEvents()

    # --- kolejne nagrania ------------------------------------------------

    def _next(self) -> None:
        run = self._queue
        if run is None:
            return
        if run.cancelled or run.index >= len(run.pending):
            self._finish(run)
            return
        recording = run.pending[run.index]
        # Wznowienie: nagranie mogło dostać szkic od wyliczenia kolejki.
        state, _message = draft_state(recording, run.recordings)
        if state != PENDING:
            self._advance(run)
            return
        if not self._open(recording, run.recordings):
            run.failed.append((recording.name, tr("series.drafts.error.open")))
            self._advance(run)
            return
        overlay = self._asr.overlay
        overlay.title_label.setText(
            tr(
                "series.drafts.busy",
                number=run.index + 1,
                total=len(run.pending),
                name=recording.name,
            )
        )
        panel = self._asr.panel
        thread = panel.create_transcription(recording, panel.decoding_options(), self)
        thread.progressed.connect(self._on_progress)
        thread.succeeded.connect(self._on_result)
        thread.failed.connect(self._on_failed)
        thread.cancelled.connect(self._on_cancelled)
        self._thread = thread
        thread.start()

    def _open(self, recording: Path, recordings: list[Path]) -> bool:
        """Nagranie w oknie: pusty projekt obok niego albo nowa transkrypcja."""
        project = project_for(recording, recordings)
        if project.is_file():
            self._session.open_project(project, confirm=False)
        else:
            self._session.new_document(confirm=False)
        current = self._audio_path()
        if current is None or current.resolve() != recording.resolve():
            self._session.import_audio(str(recording))
            current = self._audio_path()
        return current is not None and current.resolve() == recording.resolve()

    def _on_progress(self, fraction: float) -> None:
        run = self._queue
        if run is None or run.index >= len(run.durations):
            return
        current = run.durations[run.index] * min(max(fraction, 0.0), 1.0)
        self._asr.overlay.set_progress(min(1.0, (run.done_ms + current) / run.total_ms))

    def _on_result(self, result: TranscriptionResult) -> None:
        run = self._end_thread()
        if run is None:
            return
        recording = run.pending[run.index]
        if not result.text.strip():
            run.skipped.append((recording.name, tr("asr.no_speech")))
        else:
            error = self._save_draft(recording, run, result)
            if error:
                run.failed.append((recording.name, error))
            else:
                run.drafted.append(recording)
        self._advance(run)

    def _save_draft(
        self, recording: Path, run: _Queue, result: TranscriptionResult
    ) -> str:
        """Szkic w dokumencie i projekt obok nagrania; komunikat błędu albo ""."""
        self._asr.panel.restore_result(result, run.model_key)
        self._asr.insert_draft(result)
        self._session.wait_for_audio_hash()
        try:
            save_project(
                self._session.capture_state(), project_for(recording, run.recordings)
            )
        except AppError as error:
            return error.user_message
        self._session.document.mark_saved()
        return ""

    def _on_failed(self, error: AppError) -> None:
        run = self._end_thread()
        if run is not None:
            run.failed.append((run.pending[run.index].name, error.user_message))
            self._advance(run)

    def _on_cancelled(self) -> None:
        run = self._end_thread()
        if run is not None:
            run.cancelled = True
            self._finish(run)

    def _end_thread(self) -> _Queue | None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.wait(5000)
            thread.deleteLater()
        return self._queue

    def _advance(self, run: _Queue) -> None:
        run.done_ms += run.durations[run.index]
        run.index += 1
        self._asr.overlay.set_progress(min(1.0, run.done_ms / run.total_ms))
        QTimer.singleShot(0, self._next)

    def _finish(self, run: _Queue) -> None:
        self._queue = None
        self._asr.overlay.cancel_requested.disconnect(self.cancel)
        self._asr.overlay.title_label.setText(tr("loading.title"))
        self._asr.transcription_finished()
        if run.drafted:
            self._session.new_document(confirm=False)
            self._open_recording(run.drafted[0])
        self.show_message(tr("series.drafts.title"), summary_text(run))

    # --- okna ------------------------------------------------------------

    def _downloaded_models(self) -> list[AsrModelInfo]:
        manager = self._asr.panel.manager
        return [model for model in MODELS if manager.with_model(model).is_downloaded()]

    def _dialog(self, models: list[AsrModelInfo], summary: str) -> SeriesDraftsDialog:
        panel = self._asr.panel
        options = panel.decoding_options()
        return SeriesDraftsDialog(
            models,
            panel.model.key,
            (options.speakers or 0) if options.diarize else None,
            summary,
            self._window,
        )

    def _show_message(self, title: str, text: str) -> None:
        QMessageBox.information(self._window, title, text)


def summary_text(run: _Queue) -> str:
    """Podsumowanie kolejki: gotowe szkice, błędy i pominięte nagrania."""
    lines = [tr("series.drafts.summary.done", count=len(run.drafted))]
    if run.cancelled:
        lines.append(tr("series.drafts.summary.cancelled"))
    if run.failed:
        lines.append("")
        lines.append(tr("series.drafts.summary.failed"))
        lines.extend(f"• {name}: {message}" for name, message in run.failed)
    if run.skipped:
        lines.append("")
        lines.append(tr("series.drafts.summary.skipped"))
        lines.extend(f"• {name}: {message}" for name, message in run.skipped)
    return "\n".join(lines)


__all__ = ["SeriesDrafts", "summary_text"]
