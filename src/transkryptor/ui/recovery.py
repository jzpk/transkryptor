"""ACC-30: odzyskanie pracy z osieroconych autozapisów przy starcie programu."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QWidget

from transkryptor.document.project import ProjectState
from transkryptor.ui.autosave import AutosaveController, RecoveryDialog, find_orphans

# Nagranie i jego suma dla stanu projektu (``AudioLocator.locate``).
LocateAudio = Callable[[ProjectState, Path | None], tuple[Path | None, str | None]]
# Zastąpienie bieżącej pracy odzyskanym stanem (nagranie, jego suma).
ApplyRecovered = Callable[[ProjectState, Path | None, str | None], None]


class RecoveryController:
    """Proponuje odzyskanie autozapisu z poprzedniej (przerwanej) sesji."""

    def __init__(
        self,
        parent: QWidget,
        autosave: AutosaveController,
        locate_audio: LocateAudio,
        apply: ApplyRecovered,
    ) -> None:
        self._parent = parent
        self._autosave = autosave
        self._locate_audio = locate_audio
        self._apply = apply

    def offer(self) -> bool:
        """Pokazuje okno odzyskiwania; True, gdy praca została odzyskana."""
        autosave = self._autosave
        candidates = find_orphans(autosave.directory, autosave.session_id)
        if not candidates:
            return False
        dialog = RecoveryDialog(candidates, self._parent)
        dialog.exec()
        chosen = dialog.chosen
        for candidate in dialog.candidates:
            if candidate is not chosen:
                candidate.release()
        if chosen is None or chosen.state is None:
            return False
        state = chosen.state
        audio, sha256 = self._locate_audio(state, None)
        self._apply(state, audio, sha256)
        # Odzyskana praca ma swój autozapis w bieżącej sesji.
        chosen.remove()
        autosave.save_now()
        return True


__all__ = ["RecoveryController"]
