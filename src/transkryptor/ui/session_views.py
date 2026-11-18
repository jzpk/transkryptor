"""Widoki, z których korzysta sesja - jako wąskie ``Protocol``, nie widżety.

``SessionController`` i ``ProjectStateMapper`` znają tylko metody potrzebne
do zapisu, odczytu i ochrony pracy. Okno podaje swoje widżety
(``TranscriptionEditor``, ``AudioPlayer``, ``PlayerBar``, ``AsrPanel``),
a testy mogą podać imitacje bez budowania całego okna.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from transkryptor.asr.results import TranscriptionResult
from transkryptor.document.model import Document
from transkryptor.document.project import PlayerState
from transkryptor.ui.metadata_form import MetadataWidgets


class EditorView(Protocol):
    def load_content(
        self,
        text: str,
        superscript_ranges: Iterable[tuple[int, int]],
        paragraph_speakers: dict[int, str] | None = None,
    ) -> None: ...

    def sync_to_document(self, doc: Document) -> bool: ...

    def clear(self) -> None: ...

    def blockSignals(self, b: bool) -> bool: ...


class PlayerView(Protocol):
    @property
    def source_path(self) -> Path | None: ...

    def load(self, path: str | Path) -> None: ...

    def stop_and_unload(self) -> None: ...


class PlayerBarView(Protocol):
    def reset(self) -> None: ...

    def state(self) -> PlayerState: ...

    def restore_state(self, state: PlayerState) -> None: ...


class AsrView(Protocol):
    @property
    def last_result(self) -> TranscriptionResult | None: ...

    @property
    def last_model_key(self) -> str | None: ...

    def restore_result(
        self, result: TranscriptionResult | None, model_key: str | None = None
    ) -> None: ...

    def asr_context(self) -> tuple[str, tuple[str, ...]]: ...

    def set_asr_context(self, prompt: str, vocabulary: tuple[str, ...]) -> None: ...

    def questionnaire(self) -> tuple[str, ...]: ...

    def set_questionnaire(self, questions: tuple[str, ...]) -> None: ...

    def set_context_default(self, text: str) -> None: ...

    def set_audio_available(self, available: bool) -> None: ...

    def is_transcribing(self) -> bool: ...

    def is_downloading(self) -> bool: ...

    def cancel_download_and_wait(self, timeout_ms: int) -> bool: ...

    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class SessionViews:
    """Widoki sesji: edytor, odtwarzacz z paskiem, panel ASR i metryczka."""

    editor: EditorView
    player: PlayerView
    player_bar: PlayerBarView
    asr: AsrView
    metadata: MetadataWidgets


__all__ = [
    "AsrView",
    "EditorView",
    "PlayerBarView",
    "PlayerView",
    "SessionViews",
]
