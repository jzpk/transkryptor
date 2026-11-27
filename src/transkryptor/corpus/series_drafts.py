"""Kolejka szkiców ASR dla serii nagrań: które nagrania czekają (bez Qt).

Szkic nagrania zapisuje się od razu w projekcie obok niego
(``corpus/series.py``), więc kolejka wynika z plików i wznawia się sama:

- nagranie bez projektu albo z projektem bez szkicu i bez tekstu (np. sama
  metryczka) czeka na szkic;
- projekt ze szkicem ASR jest gotowy - ponowne uruchomienie kolejki go
  pomija;
- projekt z tekstem, ale bez szkicu (praca ręczna), nie dostaje szkicu
  bez pytania - jest pomijany;
- nieczytelny projekt jest pomijany z komunikatem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from transkryptor.corpus.series import project_for
from transkryptor.document.project import load_project
from transkryptor.errors import AppError

PENDING = "pending"
DRAFTED = "drafted"
HAS_TEXT = "has_text"
UNREADABLE = "unreadable"


@dataclass(frozen=True)
class DraftQueue:
    """Nagrania serii według stanu szkicu."""

    pending: tuple[Path, ...] = ()
    drafted: tuple[Path, ...] = ()
    with_text: tuple[Path, ...] = ()
    unreadable: tuple[tuple[Path, str], ...] = ()


def draft_state(recording: Path, recordings: Sequence[Path]) -> tuple[str, str]:
    """Stan szkicu nagrania i ewentualny komunikat błędu odczytu projektu."""
    project = project_for(recording, recordings)
    if not project.is_file():
        return PENDING, ""
    try:
        state = load_project(project)
    except AppError as error:
        return UNREADABLE, error.user_message
    if state.asr is not None:
        return DRAFTED, ""
    if state.text.strip():
        return HAS_TEXT, ""
    return PENDING, ""


def draft_queue(recordings: Sequence[Path]) -> DraftQueue:
    """Podział nagrań serii (w kolejności serii) na czekające i pozostałe."""
    groups: dict[str, list[Path]] = {PENDING: [], DRAFTED: [], HAS_TEXT: []}
    unreadable: list[tuple[Path, str]] = []
    for recording in recordings:
        state, message = draft_state(recording, recordings)
        if state == UNREADABLE:
            unreadable.append((recording, message))
        else:
            groups[state].append(recording)
    return DraftQueue(
        tuple(groups[PENDING]),
        tuple(groups[DRAFTED]),
        tuple(groups[HAS_TEXT]),
        tuple(unreadable),
    )
