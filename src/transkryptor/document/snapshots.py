"""Migawki projektu: zapisane stany pracy, do których można wrócić (bez Qt).

Migawka to pełny stan projektu (``ProjectState``) z datą, opisem
i liczbą słów, zapisany atomowo (``fileio.write_atomic``) jako plik JSON
w katalogu migawek projektu. Migawki ręczne („Zapisz migawkę…”) zostają,
dopóki użytkownik ich nie usunie; automatyczne - robione przed ryzykownymi
operacjami (wstawienie szkicu ASR, import DOCX, masowe zmiany i przywrócenie
innej migawki) - są przycinane: najwyżej ``MAX_AUTOMATIC`` najnowszych
i nie starsze niż ``MAX_AUTOMATIC_AGE``.

Katalog migawek leży w danych programu (``paths.user_data_dir()``), osobno
dla każdego pliku projektu (skrót jego ścieżki); praca bez pliku projektu
ma katalog sesji, przenoszony do katalogu projektu przy pierwszym zapisie.
Format pliku ma numer wersji (``SNAPSHOT_VERSION``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from transkryptor import paths
from transkryptor.document.project import ProjectState, from_dict, to_dict
from transkryptor.errors import ProjectError
from transkryptor.fileio import write_atomic
from transkryptor.i18n import tr

logger = logging.getLogger(__name__)

SNAPSHOT_FORMAT = "transkryptor-snapshot"
SNAPSHOT_VERSION = 1
SNAPSHOT_SUFFIX = ".json"
MAX_AUTOMATIC = 20
MAX_AUTOMATIC_AGE = timedelta(days=30)
# Migawki zawierają metryczkę (dane osobowe) - jak autozapis.
PRIVATE_MODE = 0o600


def snapshots_root() -> Path:
    """Katalog wszystkich migawek (podmieniany w testach)."""
    return paths.user_data_dir() / "snapshots"


def project_key(project_path: Path) -> str:
    """Nazwa katalogu migawek pliku projektu (skrót ścieżki bezwzględnej)."""
    digest = hashlib.sha256(str(Path(project_path).resolve()).encode("utf-8"))
    return "project-" + digest.hexdigest()[:24]


def session_key(session_id: str) -> str:
    """Nazwa katalogu migawek pracy bez pliku projektu."""
    return f"session-{session_id}"


@dataclass(frozen=True)
class Snapshot:
    """Opis migawki (bez stanu projektu - ten czyta :meth:`SnapshotStore.load`)."""

    path: Path
    created: datetime
    label: str
    automatic: bool
    word_count: int


class SnapshotStore:
    """Migawki jednego projektu w katalogu ``directory``."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def list(self) -> list[Snapshot]:
        """Migawki od najnowszej; uszkodzone pliki są pomijane."""
        found: list[Snapshot] = []
        if not self.directory.is_dir():
            return found
        for path in self.directory.glob(f"*{SNAPSHOT_SUFFIX}"):
            try:
                found.append(_describe(path, _read(path)))
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("Skipping unreadable snapshot %s", path.name)
        return sorted(found, key=lambda s: (s.created, s.path.name), reverse=True)

    def save(
        self,
        state: ProjectState,
        label: str,
        automatic: bool = False,
        now: datetime | None = None,
    ) -> Snapshot:
        """Zapisuje migawkę; błąd zapisu → ``ProjectError``."""
        created = now or datetime.now()
        data = {
            "format": SNAPSHOT_FORMAT,
            "version": SNAPSHOT_VERSION,
            "created": created.isoformat(),
            "label": label,
            "automatic": automatic,
            "word_count": state.word_count,
            "project": to_dict(state),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._free_path(created, automatic)
        payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
        write_atomic(path, payload, PRIVATE_MODE)
        if automatic:
            self.prune(created)
        return _describe(path, data)

    def load(self, snapshot: Snapshot) -> ProjectState:
        """Stan projektu z migawki; błąd odczytu → ``ProjectError``."""
        try:
            data = _read(snapshot.path)
            return from_dict(data["project"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProjectError(
                user_message=tr("snapshots.error.load", name=snapshot.path.name),
                retry_hint=tr("snapshots.error.load.hint"),
            ) from exc

    def delete(self, snapshot: Snapshot) -> None:
        with contextlib.suppress(FileNotFoundError):
            snapshot.path.unlink()

    def prune(self, now: datetime | None = None) -> None:
        """Usuwa nadmiarowe i stare migawki automatyczne (ręczne zostają)."""
        moment = now or datetime.now()
        automatic = [s for s in self.list() if s.automatic]
        for index, snapshot in enumerate(automatic):
            if index >= MAX_AUTOMATIC or moment - snapshot.created > MAX_AUTOMATIC_AGE:
                self.delete(snapshot)

    def move_to(self, directory: Path) -> SnapshotStore:
        """Przenosi migawki do ``directory`` (np. po pierwszym zapisie projektu)."""
        target = SnapshotStore(directory)
        if not self.directory.is_dir() or self.directory == directory:
            return target
        directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob(f"*{SNAPSHOT_SUFFIX}"):
            destination = directory / path.name
            if not destination.exists():
                with contextlib.suppress(OSError):
                    path.replace(destination)
        with contextlib.suppress(OSError):
            self.directory.rmdir()
        return target

    def _free_path(self, created: datetime, automatic: bool) -> Path:
        stem = created.strftime("%Y%m%d-%H%M%S") + ("-auto" if automatic else "")
        path = self.directory / f"{stem}{SNAPSHOT_SUFFIX}"
        number = 2
        while path.exists():
            path = self.directory / f"{stem}-{number}{SNAPSHOT_SUFFIX}"
            number += 1
        return path


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != SNAPSHOT_FORMAT:
        raise ValueError("to nie jest migawka projektu")
    version = data.get("version")
    if not isinstance(version, int) or not 1 <= version <= SNAPSHOT_VERSION:
        raise ValueError("nieobsługiwana wersja migawki")
    return data


def _describe(path: Path, data: dict[str, Any]) -> Snapshot:
    label = data.get("label", "")
    words = data.get("word_count", 0)
    if not isinstance(label, str) or not isinstance(words, int):
        raise TypeError("nieprawidłowy opis migawki")
    return Snapshot(
        path=path,
        created=datetime.fromisoformat(str(data["created"])),
        label=label,
        automatic=bool(data.get("automatic", False)),
        word_count=words,
    )
