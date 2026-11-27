"""Eksport wszystkich projektów serii nagrań jednym zestawem opcji.

Projekt nagrania leży obok niego (``corpus/series.py``), a plik wyjściowy
dostaje nazwę od projektu: ``w1.mp3`` → ``w1.transkr`` → ``w1.docx``
(z dopiskiem anonimizacji, gdy trzeba). Nagrania bez projektu są pomijane,
a z ``only_ready`` - także projekty, które nie są gotowe według przeglądu
serii (``corpus/series_overview.py``). Formaty z czasami pomijają projekty
bez kotwic czasowych.

Cel to katalog albo archiwum ZIP: przy ZIP-ie pliki powstają w katalogu
tymczasowym, a archiwum jest zapisywane atomowo na końcu - przerwany
eksport nie zostawia uciętego archiwum.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from transkryptor.corpus.series import project_for
from transkryptor.corpus.series_overview import (
    READY,
    ReadinessOptions,
    project_report,
    project_status,
)
from transkryptor.document.metadata import MetadataField
from transkryptor.document.model import Document
from transkryptor.document.project import (
    PROJECT_SUFFIX,
    ProjectState,
    load_project,
    resolve_audio,
)
from transkryptor.errors import AppError
from transkryptor.export.model import ExportDocument, build_export_document
from transkryptor.export.options import ExportReport
from transkryptor.export.registry import DOCX, Exporter
from transkryptor.fileio import atomic_output_raw
from transkryptor.i18n import tr

# Powody pominięcia nagrania (klucze ``series.export.skip.<powód>``).
SKIP_NO_PROJECT = "no_project"
SKIP_NOT_READY = "not_ready"
SKIP_UNREADABLE = "unreadable"
SKIP_EMPTY = "empty"
SKIP_NO_TIMES = "no_times"
SKIP_FAILED = "failed"


@dataclass(frozen=True)
class SeriesExportRequest:
    """Format, opcje i wybór projektów - raz dla całej serii."""

    exporter: Exporter
    anonymize: bool = False
    only_ready: bool = False
    fields: tuple[MetadataField, ...] = ()
    # Ustawienia raportu gotowości (``only_ready``).
    readiness: ReadinessOptions = field(default_factory=ReadinessOptions)


# Zapis modelu wyjścia do pliku (z opcjami formatu): raport eksportu.
Write = Callable[[ExportDocument, Path], ExportReport]


@dataclass(frozen=True)
class Skipped:
    """Pominięte nagranie i powód (``detail`` - np. komunikat błędu)."""

    recording: str
    reason: str
    detail: str = ""

    @property
    def text(self) -> str:
        reason = tr(f"series.export.skip.{self.reason}")
        detail = f" ({self.detail})" if self.detail else ""
        return f"{self.recording}: {reason}{detail}"


@dataclass(frozen=True)
class Exported:
    """Zapisany plik i uwagi eksportu (np. czasy interpolowane)."""

    recording: str
    file_name: str
    warnings: tuple[str, ...] = ()


def output_name(project: Path, exporter: Exporter, anonymize: bool) -> str:
    """Nazwa pliku wyjściowego od nazwy projektu (``w1.transkr`` → ``w1.docx``)."""
    base = project.name.removesuffix(PROJECT_SUFFIX)
    anonymized = tr("export.anonymized_suffix") if anonymize else ""
    return f"{base}{anonymized}{exporter.suffix}"


def planned_names(
    recordings: Sequence[Path], exporter: Exporter, anonymize: bool
) -> list[str]:
    """Nazwy plików dla nagrań, które mają projekt (np. do sprawdzenia kolizji)."""
    names = []
    for recording in recordings:
        project = project_for(recording, recordings)
        if project.is_file():
            names.append(output_name(project, exporter, anonymize))
    return names


def export_recording(
    recording: Path,
    recordings: Sequence[Path],
    request: SeriesExportRequest,
    folder: Path,
    write: Write,
) -> Exported | Skipped:
    """Plik wyjściowy projektu nagrania w ``folder`` albo powód pominięcia."""
    project = project_for(recording, recordings)
    if not project.is_file():
        return Skipped(recording.name, SKIP_NO_PROJECT)
    try:
        state = load_project(project)
    except AppError as error:
        return Skipped(recording.name, SKIP_UNREADABLE, error.user_message)
    if request.only_ready:
        status = project_status(state, project_report(state, request.readiness))
        if status != READY:
            return Skipped(recording.name, SKIP_NOT_READY)
    document = project_document(state, project, request)
    if isinstance(document, str):
        return Skipped(recording.name, document)
    name = output_name(project, request.exporter, request.anonymize)
    try:
        report = write(document, folder / name)
    except AppError as error:
        return Skipped(recording.name, SKIP_FAILED, error.user_message)
    return Exported(recording.name, name, tuple(report.warnings))


def project_document(
    state: ProjectState, project: Path, request: SeriesExportRequest
) -> ExportDocument | str:
    """Model wyjścia projektu albo powód pominięcia (pusty, bez czasów)."""
    if not state.text.strip():
        return SKIP_EMPTY
    exporter = request.exporter
    anchors = state.anchors if exporter.timed else ()
    if exporter.timed and not any(a.source != "word" for a in anchors):
        return SKIP_NO_TIMES
    document = Document(
        text=state.text,
        superscript_ranges=list(state.superscript_ranges),
        author=state.author,
        date=state.date,
        metadata=dict(state.metadata),
        speakers=list(state.speakers),
        paragraph_speakers=dict(state.paragraph_speakers),
    )
    audio = resolve_audio(state.audio, project) if state.audio is not None else None
    return build_export_document(
        document,
        request.fields,
        request.anonymize,
        anchors,
        audio,
        state.comments if exporter.key == DOCX else (),
    )


def write_zip(files: Iterable[Path], target: Path) -> None:
    """Archiwum ZIP z plikami (płasko, pod ich nazwami), zapisane atomowo."""
    with (
        atomic_output_raw(target) as handle,
        zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        for path in files:
            archive.write(path, path.name)


__all__ = [
    "Exported",
    "SeriesExportRequest",
    "Skipped",
    "output_name",
    "planned_names",
    "export_recording",
    "project_document",
    "write_zip",
]
