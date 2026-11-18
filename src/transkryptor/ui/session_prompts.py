"""Pytania sesji o zgodę na utratę lub zastąpienie pracy (REQ-09, ACC-10, BUG-01).

Same okna dialogowe - decyzję, co zrobić z odpowiedzią, podejmuje
``SessionController``.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtWidgets import QMessageBox, QWidget

from transkryptor.i18n import tr


class Discard(Enum):
    """Odpowiedź na pytanie o niezapisane zmiany."""

    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


def ask_discard(parent: QWidget, project_name: str | None) -> Discard:
    """Dokument z plikiem pyta o niezapisane zmiany, bez pliku - o niewyeksportowane."""
    if project_name is not None:
        title = tr("session.unsaved.title")
        text = tr("session.unsaved.text", name=project_name)
    else:
        title = tr("session.discard.title")
        text = tr("session.discard.text")
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer == QMessageBox.StandardButton.Save:
        return Discard.SAVE
    if answer == QMessageBox.StandardButton.Discard:
        return Discard.DISCARD
    return Discard.CANCEL


def confirm_audio_change(
    parent: QWidget, name: str, *, has_asr: bool, has_anchors: bool, has_verified: bool
) -> bool:
    """Zmiana nagrania usuwa szkic ASR, kotwice i sprawdzone zakresy."""
    text = tr("session.change_audio.text", name=name)
    if has_asr:
        text = f"{text}\n\n{tr('session.change_audio.asr')}"
    if has_anchors:
        text = f"{text}\n\n{tr('session.change_audio.anchors')}"
    if has_verified:
        text = f"{text}\n\n{tr('session.change_audio.verified')}"
    answer = QMessageBox.question(
        parent,
        tr("session.change_audio.title"),
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Yes


def tell_transcribing(parent: QWidget) -> None:
    """Okna nie da się zamknąć w trakcie transkrypcji."""
    QMessageBox.information(
        parent, tr("session.transcribing.title"), tr("session.transcribing.text")
    )


def confirm_stop_download(parent: QWidget) -> bool:
    """Zamknięcie okna przerwie pobieranie modelu."""
    answer = QMessageBox.question(
        parent,
        tr("session.downloading.title"),
        tr("session.downloading.text"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def tell_download_busy(parent: QWidget) -> None:
    """Pobieranie nie zatrzymało się na czas - okno zostaje otwarte."""
    QMessageBox.information(
        parent, tr("session.downloading.title"), tr("session.downloading.busy")
    )


__all__ = [
    "Discard",
    "ask_discard",
    "confirm_audio_change",
    "confirm_stop_download",
    "tell_download_busy",
    "tell_transcribing",
]
