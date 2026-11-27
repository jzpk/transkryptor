"""Przegląd serii nagrań: stan każdego nagrania folderu serii (bez Qt).

Seria nie ma osobnego pliku opisu, więc stan nagrania wynika z projektu
obok niego (``corpus/series.py``):

- ``NO_PROJECT`` - nagranie bez projektu;
- ``DRAFT`` - projekt ma szkic ASR, a tekst jest taki, jak po jego
  wstawieniu (nikt go jeszcze nie poprawiał);
- ``READY`` - raport gotowości (``document/readiness.py``) nie ma pozycji:
  bez ostrzeżeń walidatora, niesprawdzonych niepewnych słów, otwartych
  komentarzy, akapitów bez mówcy i pustych pól metryczki;
- ``IN_PROGRESS`` - pozostałe projekty z tekstem;
- ``UNREADABLE`` - pliku projektu nie da się odczytać.

Pokrycie nagrania tekstem i czas pracy to te same dane co w oknie
„Statystyki projektu” (``document/progress.py``, ``work_log.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from transkryptor.audio.probe import duration_ms
from transkryptor.corpus.series import project_for, series_recordings
from transkryptor.document.metadata import MetadataField
from transkryptor.document.progress import covered_ms
from transkryptor.document.project import ProjectState, load_project
from transkryptor.document.readiness import ReadinessReport, build_report
from transkryptor.errors import AppError
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.notation.validator import NotationWarning, validate
from transkryptor.settings import Settings

NO_PROJECT = "no_project"
DRAFT = "draft"
IN_PROGRESS = "in_progress"
READY = "ready"
UNREADABLE = "unreadable"
STATUSES = (NO_PROJECT, DRAFT, IN_PROGRESS, READY, UNREADABLE)

# ``progress(done, total)`` przy kolejnych nagraniach; False - przerwij.
Progress = Callable[[int, int], bool]


@dataclass(frozen=True)
class ReadinessOptions:
    """Ustawienia, z którymi liczony jest raport gotowości projektu."""

    fields: tuple[MetadataField, ...] = ()
    ellipsis: EllipsisStyle | None = None
    enabled_rules: Collection[str] | None = None
    # Próg pewności słowa szkicu; None - niepewne słowa nie są zgłaszane.
    uncertain_threshold: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> ReadinessOptions:
        asr = settings.asr
        return cls(
            fields=tuple(settings.metadata.fields),
            ellipsis=settings.notation.ellipsis,
            enabled_rules=settings.validator.enabled,
            uncertain_threshold=(
                asr.word_threshold if asr.show_uncertain_words else None
            ),
        )


@dataclass(frozen=True)
class SeriesRow:
    """Wiersz przeglądu: nagranie serii i stan jego projektu."""

    recording: Path
    status: str
    project: Path | None = None
    duration_ms: int | None = None
    covered_ms: int = 0
    modified: datetime | None = None
    work_seconds: int = 0
    # Pozycje raportu gotowości (co zostało do zrobienia).
    issues: int = 0
    error: str = ""

    @property
    def coverage(self) -> float | None:
        """Część nagrania pokryta tekstem (None - nieznana długość)."""
        if not self.duration_ms:
            return None
        return min(1.0, self.covered_ms / self.duration_ms)


@dataclass(frozen=True)
class SeriesOverview:
    folder: Path
    rows: tuple[SeriesRow, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> int:
        return sum(1 for row in self.rows if row.status == READY)

    @property
    def duration_ms(self) -> int:
        return sum(row.duration_ms or 0 for row in self.rows)

    @property
    def covered_ms(self) -> int:
        return sum(min(row.covered_ms, row.duration_ms or 0) for row in self.rows)


class OverviewCancelled(Exception):
    """Przegląd przerwany przez użytkownika."""


def series_overview(
    folder: Path, options: ReadinessOptions, progress: Progress | None = None
) -> SeriesOverview:
    """Stan wszystkich nagrań folderu serii, w kolejności serii."""
    recordings = series_recordings(folder)
    rows: list[SeriesRow] = []
    for index, recording in enumerate(recordings):
        if progress is not None and not progress(index, len(recordings)):
            raise OverviewCancelled
        rows.append(recording_row(recording, recordings, options))
    return SeriesOverview(folder, tuple(rows))


def recording_row(
    recording: Path, recordings: list[Path], options: ReadinessOptions
) -> SeriesRow:
    """Wiersz przeglądu jednego nagrania serii."""
    project = project_for(recording, recordings)
    if not project.is_file():
        return SeriesRow(recording, NO_PROJECT, duration_ms=duration_ms(recording))
    try:
        state = load_project(project)
        modified = datetime.fromtimestamp(project.stat().st_mtime)
    except (AppError, OSError) as error:
        message = error.user_message if isinstance(error, AppError) else str(error)
        return SeriesRow(
            recording,
            UNREADABLE,
            project,
            duration_ms=duration_ms(recording),
            error=message,
        )
    report = project_report(state, options)
    return SeriesRow(
        recording,
        project_status(state, report),
        project,
        duration_ms=state.work.audio_duration_ms or duration_ms(recording),
        covered_ms=covered_ms(state.text, state.anchors),
        modified=modified,
        work_seconds=state.work.seconds,
        issues=len(report.issues),
    )


def project_status(state: ProjectState, report: ReadinessReport) -> str:
    if state.asr is not None:
        baseline = state.draft_baseline
        draft = baseline.text if baseline is not None else state.asr.text
        if state.text == draft:
            return DRAFT
    if state.text.strip() and report.is_ready:
        return READY
    return IN_PROGRESS


def project_report(state: ProjectState, options: ReadinessOptions) -> ReadinessReport:
    """Raport gotowości z danych zapisanych w projekcie."""
    threshold = options.uncertain_threshold
    uncertain = (
        [(a.start, a.end) for a in state.anchors if a.is_uncertain(threshold)]
        if threshold is not None
        else []
    )
    return build_report(
        state.text,
        _warnings(state, options),
        uncertain,
        state.comments,
        state.paragraph_speakers,
        state.metadata,
        options.fields,
    )


def _warnings(state: ProjectState, options: ReadinessOptions) -> list[NotationWarning]:
    """Ostrzeżenia walidatora bez zignorowanych w projekcie („Ignoruj tutaj”)."""
    warnings = validate(
        state.text,
        options.ellipsis,
        state.superscript_ranges,
        options.enabled_rules,
        state.paragraph_speakers,
    )
    ignored = {
        (entry.code, entry.start, entry.end)
        for entry in state.ignored_warnings
        if state.text[entry.start : entry.end] == entry.text
    }
    return [w for w in warnings if (w.code, w.start, w.end) not in ignored]
