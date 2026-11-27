"""Seria nagrań: folder z nagraniami transkrybowanymi po kolei (bez Qt).

Seria to zwykły folder z nagraniami - bez osobnego pliku opisu. Projekt
nagrania leży obok niego pod tą samą nazwą (``wywiad_01.mp3`` →
``wywiad_01.transkr``), więc kolejność i postęp serii wynikają z samych
plików: następne nagranie to kolejne w porządku naturalnym nazw
(``wywiad_2`` przed ``wywiad_10``), a gotowe - to, które ma projekt.
Folder serii jest też zwykłym folderem korpusu (``corpus/projects.py``).

:func:`extract_series` rozpakowuje do folderu nagrania z archiwum ZIP.
Bierze tylko pliki obsługiwanych formatów, pod bezpiecznymi nazwami (bez
katalogów z archiwum, ``safe_name``), z limitem rozmiaru elementu, i zapisuje
je atomowo - przerwane rozpakowanie nie zostawia uciętego nagrania. Nagranie
o tej samej nazwie i rozmiarze, które już jest w folderze (ponowny import
tego samego archiwum), zostaje bez zmian; inny plik o tej nazwie dostaje
nazwę z numerem (``wywiad (2).mp3``).
"""

from __future__ import annotations

import math
import re
import shutil
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from transkryptor.audio.formats import SUPPORTED_FORMATS_LABEL, is_audio
from transkryptor.document.pack_checks import safe_name
from transkryptor.document.project import PROJECT_SUFFIX
from transkryptor.errors import ProjectError
from transkryptor.fileio import SizeLimitError, atomic_output_raw, limited_chunks
from transkryptor.i18n import tr

ZIP_SUFFIX = ".zip"
# Największe nagranie w archiwum i zapas wolnego miejsca po rozpakowaniu.
MAX_RECORDING_BYTES = 16 * 1024**3
DISK_MARGIN_BYTES = 256 * 1024 * 1024
_COPY_CHUNK = 1 << 20
_DIGITS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class SeriesImport:
    """Wynik rozpakowania: nagrania serii i pominięte pliki archiwum."""

    folder: Path
    recordings: tuple[Path, ...]
    # Nowo rozpakowane nagrania (bez tych, które już były w folderze).
    extracted: tuple[Path, ...]
    skipped: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeriesPosition:
    """Miejsce nagrania w serii (numer od 1) i liczba gotowych projektów."""

    number: int
    total: int
    done: int
    next_recording: Path | None


def natural_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Klucz sortowania nazw z liczbami po wartości (``2`` przed ``10``)."""
    parts = _DIGITS.split(path.name.casefold())
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in parts if part
    )


def series_recordings(folder: Path) -> list[Path]:
    """Nagrania w folderze (bez podfolderów i plików ukrytych), po kolei."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    recordings = [
        entry
        for entry in entries
        if not entry.name.startswith(".") and is_audio(entry) and entry.is_file()
    ]
    return sorted(recordings, key=natural_key)


def project_for(recording: Path, recordings: Sequence[Path] = ()) -> Path:
    """Plik projektu nagrania w folderze serii.

    Zwykle ``<nazwa>.transkr``; gdy w serii jest inne nagranie o tej samej
    nazwie bez rozszerzenia (``a.mp3`` i ``a.wav``), projekt zachowuje
    rozszerzenie nagrania (``a.mp3.transkr``), żeby się nie nadpisywały.
    """
    stem = recording.stem.casefold()
    twins = [
        other
        for other in recordings
        if other.stem.casefold() == stem and other.name != recording.name
    ]
    if twins:
        return recording.with_name(f"{recording.name}{PROJECT_SUFFIX}")
    return recording.with_suffix(PROJECT_SUFFIX)


def series_position(recording: Path) -> SeriesPosition | None:
    """Miejsce nagrania w serii jego folderu (None - nagranie poza serią).

    Serią jest folder z co najmniej dwoma nagraniami.
    """
    recordings = series_recordings(recording.parent)
    names = [path.name for path in recordings]
    if len(recordings) < 2 or recording.name not in names:
        return None
    index = names.index(recording.name)
    done = sum(1 for path in recordings if project_for(path, recordings).is_file())
    following = recordings[index + 1] if index + 1 < len(recordings) else None
    return SeriesPosition(index + 1, len(recordings), done, following)


def first_unfinished(recordings: Sequence[Path]) -> Path | None:
    """Pierwsze nagranie bez projektu, a gdy wszystkie mają - pierwsze."""
    for recording in recordings:
        if not project_for(recording, recordings).is_file():
            return recording
    return recordings[0] if recordings else None


# --- rozpakowanie archiwum -----------------------------------------------------


def extract_series(archive_path: Path, folder: Path) -> SeriesImport:
    """Rozpakowuje nagrania z archiwum ZIP do ``folder`` (tworzy go, gdy trzeba).

    Błąd odczytu archiwum, zapisu albo brak nagrań → ``ProjectError``.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            members, skipped = _audio_members(archive)
            if not members:
                raise _no_recordings(archive_path)
            _check_space(members, folder)
            extracted = _extract_all(archive, members, folder)
    except ProjectError:
        raise
    except SizeLimitError as exc:
        raise _invalid(archive_path) from exc
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise _invalid(archive_path, exc) from exc
    return SeriesImport(
        folder,
        tuple(series_recordings(folder)),
        tuple(extracted),
        tuple(skipped),
    )


def _audio_members(
    archive: zipfile.ZipFile,
) -> tuple[list[zipfile.ZipInfo], list[str]]:
    """Nagrania w archiwum (po kolei) i nazwy pominiętych plików.

    Pomija katalogi, pliki ukryte i systemowe (``__MACOSX``, ``.DS_Store``)
    bez wymieniania ich - użytkownik ich nie widzi w archiwum.
    """
    members: list[zipfile.ZipInfo] = []
    skipped: list[str] = []
    for info in archive.infolist():
        parts = PurePosixPath(info.filename.replace("\\", "/")).parts
        if info.is_dir() or not parts:
            continue
        if any(part.startswith(".") or part == "__MACOSX" for part in parts):
            continue
        if is_audio(parts[-1]) and safe_name(parts[-1]):
            members.append(info)
        else:
            skipped.append(parts[-1])
    members.sort(key=lambda info: natural_key(Path(info.filename)))
    return members, skipped


def _check_space(members: Sequence[zipfile.ZipInfo], folder: Path) -> None:
    """Nagrania mieszczą się w limicie elementu i na dysku (z zapasem)."""
    for info in members:
        if info.file_size > MAX_RECORDING_BYTES:
            raise SizeLimitError(MAX_RECORDING_BYTES)
    needed = sum(info.file_size for info in members)
    if needed + DISK_MARGIN_BYTES > shutil.disk_usage(folder).free:
        raise ProjectError(
            user_message=tr(
                "series.error.no_space", size=math.ceil(needed / (1024 * 1024))
            ),
            retry_hint=tr("series.error.no_space.hint"),
        )


def _extract_all(
    archive: zipfile.ZipFile, members: Sequence[zipfile.ZipInfo], folder: Path
) -> list[Path]:
    taken: set[str] = set()
    extracted: list[Path] = []
    for info in members:
        name = safe_name(PurePosixPath(info.filename.replace("\\", "/")).name)
        target = _target(folder, name, info.file_size, taken)
        taken.add(target.name.casefold())
        if target.is_file() and target.stat().st_size == info.file_size:
            continue  # to samo nagranie z wcześniejszego importu
        _extract(archive, info, target)
        extracted.append(target)
    return extracted


def _target(folder: Path, name: str, size: int, taken: set[str]) -> Path:
    """Wolna nazwa w folderze: ta sama albo z numerem (``a (2).mp3``).

    Istniejący plik o tym samym rozmiarze to nagranie z poprzedniego importu
    - zostaje pod swoją nazwą (i nie jest rozpakowywany ponownie).
    """
    path = Path(name)
    number = 1
    while True:
        candidate = folder / (
            name if number == 1 else f"{path.stem} ({number}){path.suffix}"
        )
        if candidate.name.casefold() not in taken and (
            not candidate.exists()
            or (candidate.is_file() and candidate.stat().st_size == size)
        ):
            return candidate
        number += 1


def _extract(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    """Element archiwum zapisany atomowo; dłuższy niż w nagłówku → błąd."""
    with archive.open(info) as source, atomic_output_raw(target) as handle:
        chunks = iter(lambda: source.read(_COPY_CHUNK), b"")
        for chunk in limited_chunks(chunks, info.file_size):
            handle.write(chunk)


def _no_recordings(path: Path) -> ProjectError:
    return ProjectError(
        user_message=tr(
            "series.error.empty", name=path.name, formats=SUPPORTED_FORMATS_LABEL
        ),
        retry_hint=tr("series.error.empty.hint"),
    )


def _invalid(path: Path, exc: Exception | None = None) -> ProjectError:
    reason = (exc.strerror if isinstance(exc, OSError) else None) or exc or ""
    return ProjectError(
        user_message=tr("series.error.invalid", name=path.name, reason=reason),
        retry_hint=tr("series.error.invalid.hint"),
    )
