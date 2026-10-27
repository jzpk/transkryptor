"""Błąd niepoprawnego pliku projektu (składnia albo schemat)."""

from __future__ import annotations

from transkryptor.errors import ProjectError
from transkryptor.i18n import tr


class InvalidProjectError(ProjectError):
    """Plik nie jest poprawnym projektem (składnia albo schemat)."""


def invalid(name: str = "") -> InvalidProjectError:
    return InvalidProjectError(
        user_message=(
            tr("project.error.invalid_named", name=name)
            if name
            else tr("project.error.invalid")
        ),
        retry_hint=tr("project.error.invalid.hint"),
    )
