"""Zapis i odczyt pliku projektu (atomowo, z migracją schematu)."""

from __future__ import annotations

from pathlib import Path

from transkryptor.document.project.codec import dumps, loads
from transkryptor.document.project.errors import InvalidProjectError, invalid
from transkryptor.document.project.model import ProjectState
from transkryptor.errors import ProjectError
from transkryptor.fileio import write_atomic
from transkryptor.i18n import tr


def save_project(state: ProjectState, path: str | Path) -> None:
    """Zapisuje projekt atomowo; błąd zapisu → ``ProjectError``."""
    target = Path(path)
    write_atomic(target, dumps(state, target).encode("utf-8"))


def load_project(path: str | Path) -> ProjectState:
    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ProjectError(
            user_message=tr(
                "project.error.open", name=source.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("project.error.open.hint"),
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise invalid(source.name) from exc
    try:
        return loads(text)
    except InvalidProjectError as error:
        raise invalid(source.name) from error
