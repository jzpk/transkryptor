"""Projekty korpusu: pliki ``.transkr`` w folderze i podfolderach (bez Qt).

Korpus to zwykły folder z projektami - bez osobnego pliku opisu. Skan
czyta każdy projekt przez ``load_project`` (z migracją starszych schematów),
a pliki, których nie da się odczytać, zbiera osobno z komunikatem, żeby
jeden uszkodzony projekt nie blokował pracy na reszcie.

``overrides`` podmienia stan wskazanych plików - okno podaje tak bieżący
projekt z niezapisanymi zmianami, żeby wyszukiwanie widziało to, co jest
w edytorze.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from transkryptor.document.project import (
    PROJECT_SUFFIX,
    ProjectState,
    load_project,
    resolve_audio,
)
from transkryptor.errors import AppError


@dataclass(frozen=True)
class CorpusProject:
    """Projekt korpusu; ``path`` None - bieżący dokument bez pliku projektu."""

    path: Path | None
    state: ProjectState
    # Nazwa pokazywana zamiast ścieżki (bieżący dokument bez pliku).
    title: str = ""

    @property
    def name(self) -> str:
        if self.path is not None:
            return self.path.stem
        return self.title

    def relative_name(self, folder: Path | None) -> str:
        """Ścieżka względem folderu korpusu (zapis POSIX) albo nazwa."""
        if self.path is None:
            return self.title
        if folder is not None:
            try:
                return self.path.relative_to(folder).as_posix()
            except ValueError:
                pass
        return self.path.name

    def audio_path(self) -> Path | None:
        """Istniejący plik nagrania projektu (None - brak albo nie znaleziono)."""
        if self.state.audio is None:
            return None
        return resolve_audio(self.state.audio, self.path)


@dataclass(frozen=True)
class ScanError:
    path: Path
    message: str


@dataclass(frozen=True)
class ScanResult:
    folder: Path
    projects: tuple[CorpusProject, ...]
    errors: tuple[ScanError, ...] = ()


def find_projects(folder: str | Path) -> list[Path]:
    """Pliki projektów w folderze i podfolderach, posortowane po ścieżce.

    Pomija pliki i foldery ukryte (zaczynające się od kropki) - tam trafiają
    m.in. pliki tymczasowe zapisu atomowego.
    """
    root = Path(folder)
    found: list[Path] = []
    for path in root.rglob(f"*{PROJECT_SUFFIX}"):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_file():
            found.append(path)
    return sorted(found, key=lambda path: path.relative_to(root).as_posix().lower())


def scan_folder(
    folder: str | Path,
    overrides: Mapping[Path, ProjectState] | None = None,
    progress: Callable[[int, int], bool] | None = None,
) -> ScanResult:
    """Czyta projekty folderu; ``progress(done, total)`` False przerywa skan.

    Klucze ``overrides`` porównywane są po ścieżce rozwiązanej (``resolve``).
    """
    root = Path(folder)
    replaced = {path.resolve(): state for path, state in (overrides or {}).items()}
    paths = find_projects(root)
    projects: list[CorpusProject] = []
    errors: list[ScanError] = []
    for index, path in enumerate(paths):
        if progress is not None and not progress(index, len(paths)):
            break
        state = replaced.get(path.resolve())
        if state is None:
            try:
                state = load_project(path)
            except AppError as error:
                errors.append(ScanError(path, error.user_message))
                continue
        projects.append(CorpusProject(path, state))
    return ScanResult(root, tuple(projects), tuple(errors))
