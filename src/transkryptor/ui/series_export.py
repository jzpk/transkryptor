"""Eksport całej serii nagrań (``export/series_export.py``) w oknie programu.

Okno opcji (``ui/series_export_dialog.py``) pyta raz o format, opcje i cel.
Projekty są eksportowane po jednym, z przerwą na zdarzenia okna między
nimi: nakładka pokazuje postęp, a „Przerwij” zatrzymuje eksport po bieżącym
pliku. Na koniec okno podsumowania: ile plików powstało, które nagrania
pominięto i dlaczego, oraz uwagi eksportu (np. czasy interpolowane).
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from transkryptor.corpus.series import series_recordings
from transkryptor.corpus.series_overview import ReadinessOptions
from transkryptor.errors import ExportError
from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.registry import run_export
from transkryptor.export.series_export import (
    Exported,
    SeriesExportRequest,
    Skipped,
    export_recording,
    planned_names,
    write_zip,
)
from transkryptor.i18n import tr
from transkryptor.settings import Settings
from transkryptor.ui.busy_overlay import BusyOverlay, InputBlocker
from transkryptor.ui.export_controller import ExportController
from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.messages import show_error
from transkryptor.ui.series_export_dialog import SeriesExportDialog


@dataclass
class _Run:
    """Trwający eksport: kolejka nagrań, katalog plików i wyniki."""

    recordings: list[Path]
    request: SeriesExportRequest
    options: ExportOptions
    work_dir: Path
    # Archiwum docelowe (None - pliki od razu w ``work_dir``).
    archive: Path | None
    done: int = 0
    cancelled: bool = False
    exported: list[Exported] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)


class SeriesExporter(QObject):
    """„Eksportuj serię…”: opcje, cel, eksport po kolei i podsumowanie."""

    def __init__(
        self,
        window: QWidget,
        exports: ExportController,
        settings: Callable[[], Settings],
        show_status: Callable[[str], None],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._exports = exports
        self._settings = settings
        self._show_status = show_status
        self._run: _Run | None = None
        self.overlay = BusyOverlay(window)
        self.overlay.setObjectName("series_export_overlay")
        self.overlay.cancel_requested.connect(self.cancel)
        self._blocker = InputBlocker((self.overlay.cancel_button,), self)
        # Okna wyboru i pytania; testy podstawiają gotowe odpowiedzi.
        self.run_dialog: Callable[[SeriesExportDialog], int] = lambda d: d.exec()
        self.choose_folder: Callable[[Path], Path | None] = self._choose_folder
        self.choose_archive: Callable[[Path, str], Path | None] = self._choose_archive
        self.confirm_overwrite: Callable[[list[str]], bool] = self._confirm_overwrite
        self.show_summary: Callable[[str, str], None] = self._show_summary

    @property
    def busy(self) -> bool:
        return self._run is not None

    def start(self, folder: Path) -> bool:
        """Pyta o opcje i cel, potem zaczyna eksport; False - rezygnacja."""
        if self._run is not None:
            return False
        recordings = series_recordings(folder)
        format_key, initial = self._exports.initial_choice()
        dialog = SeriesExportDialog(
            format_key,
            initial,
            self._exports.pos_available,
            len(recordings),
            self._window,
        )
        if self.run_dialog(dialog) != SeriesExportDialog.DialogCode.Accepted:
            return False
        options = dialog.options()
        self._exports.remember(dialog.exporter, options)
        request = SeriesExportRequest(
            dialog.exporter,
            dialog.anonymize,
            dialog.only_ready,
            self._exports.fields(),
            ReadinessOptions.from_settings(self._settings()),
        )
        run = self._prepare(folder, recordings, request, options, dialog.to_zip)
        if run is None:
            return False
        self._run = run
        self._blocker.start()
        self.overlay.start(tr("series.export.busy", count=len(recordings)))
        self.overlay.set_progress(0, len(recordings))
        QTimer.singleShot(0, self._step)
        return True

    def cancel(self) -> None:
        if self._run is not None:
            self._run.cancelled = True

    def wait(self) -> None:
        """Czeka na koniec eksportu (testy)."""
        while self._run is not None:
            QApplication.processEvents()

    # --- etapy -----------------------------------------------------------

    def _prepare(
        self,
        folder: Path,
        recordings: list[Path],
        request: SeriesExportRequest,
        options: ExportOptions,
        to_zip: bool,
    ) -> _Run | None:
        """Cel eksportu: katalog (z pytaniem o nadpisanie) albo ZIP."""
        if to_zip:
            archive = self.choose_archive(folder.parent, f"{folder.name}.zip")
            if archive is None:
                return None
            try:
                work_dir = Path(
                    tempfile.mkdtemp(prefix=".transkr-", dir=archive.parent)
                )
            except OSError as exc:
                self._show_write_error(archive, exc)
                return None
            return _Run(recordings, request, options, work_dir, archive)
        target = self.choose_folder(folder)
        if target is None:
            return None
        names = planned_names(recordings, request.exporter, request.anonymize)
        existing = [name for name in names if (target / name).exists()]
        if existing and not self.confirm_overwrite(existing):
            return None
        return _Run(recordings, request, options, target, None)

    def _step(self) -> None:
        run = self._run
        if run is None:
            return
        if run.cancelled or run.done >= len(run.recordings):
            self._finish(run)
            return
        recording = run.recordings[run.done]
        result = export_recording(
            recording, run.recordings, run.request, run.work_dir, self._writer(run)
        )
        if isinstance(result, Exported):
            run.exported.append(result)
        else:
            run.skipped.append(result)
        run.done += 1
        self.overlay.set_progress(run.done, len(run.recordings))
        QTimer.singleShot(0, self._step)

    def _writer(self, run: _Run) -> Callable[[ExportDocument, Path], ExportReport]:
        exporter = run.request.exporter
        options = self._exports.file_options(run.options)

        def write(document: ExportDocument, path: Path) -> ExportReport:
            highlighted = self._exports.highlight(
                document, exporter, options.parts_of_speech
            )
            return run_export(exporter, highlighted, path, options)

        return write

    def _finish(self, run: _Run) -> None:
        self._run = None
        self.overlay.stop()
        self._blocker.stop()
        target = run.archive or run.work_dir
        try:
            if run.archive is not None and not run.cancelled and run.exported:
                files = [run.work_dir / item.file_name for item in run.exported]
                try:
                    write_zip(files, run.archive)
                except OSError as exc:
                    self._show_write_error(run.archive, exc)
                    return
        finally:
            if run.archive is not None:
                shutil.rmtree(run.work_dir, ignore_errors=True)
        if run.cancelled and run.archive is not None:
            # Archiwum nie powstało - nie ma czego podsumowywać.
            self._show_status(tr("series.export.cancelled"))
            return
        self._show_status(
            tr("series.export.done", count=len(run.exported), target=target.name)
        )
        self.show_summary(summary_text(run, target), details_text(run))

    def _show_write_error(self, path: Path, exc: OSError) -> None:
        error = ExportError(
            user_message=tr(
                "docx_export.error.write", name=path.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("docx_export.error.write.hint"),
        )
        show_error(self._window, tr("series.export.error"), error)

    # --- okna ------------------------------------------------------------

    def _choose_folder(self, start: Path) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(
            self._window, tr("series.export.folder_dialog"), str(start)
        )
        return Path(chosen) if chosen else None

    def _choose_archive(self, start: Path, name: str) -> Path | None:
        return ask_save_path(
            self._window,
            tr("series.export.zip_dialog"),
            str(start / name),
            tr("series.import.filter", patterns="*.zip"),
            ".zip",
        )

    def _confirm_overwrite(self, existing: list[str]) -> bool:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            tr("series.export.overwrite.title"),
            tr("series.export.overwrite.text", count=len(existing)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            self._window,
        )
        box.setDetailedText("\n".join(existing))
        return box.exec() == QMessageBox.StandardButton.Yes

    def _show_summary(self, text: str, details: str) -> None:
        box = QMessageBox(
            QMessageBox.Icon.Information,
            tr("series.export.summary.title"),
            text,
            QMessageBox.StandardButton.Ok,
            self._window,
        )
        if details:
            box.setDetailedText(details)
        box.exec()


def summary_text(run: _Run, target: Path) -> str:
    """Ile plików powstało i ile nagrań pominięto."""
    text = tr(
        "series.export.summary.text",
        count=len(run.exported),
        target=str(target),
        skipped=len(run.skipped),
    )
    if run.cancelled:
        text += "\n\n" + tr("series.export.summary.cancelled")
    if any(item.warnings for item in run.exported):
        text += "\n\n" + tr("series.export.summary.warnings")
    return text


def details_text(run: _Run) -> str:
    """Pominięte nagrania z powodami i uwagi eksportu plików."""
    parts: list[str] = []
    if run.skipped:
        parts.append(tr("series.export.summary.skipped"))
        parts.extend(f"• {item.text}" for item in run.skipped)
    for item in run.exported:
        if item.warnings:
            parts.append("")
            parts.append(f"{item.file_name}:")
            parts.extend(item.warnings)
    return "\n".join(parts).strip()


__all__ = ["SeriesExporter", "details_text", "summary_text"]
