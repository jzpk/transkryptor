"""Wątek transkrypcji ASR: wywołanie silnika w tle z postępem i anulowaniem."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from transkryptor.asr import engine
from transkryptor.asr.engine import DecodingOptions, TranscriptionResult
from transkryptor.asr.models import AsrModelInfo
from transkryptor.errors import AppError


class TranscribeThread(QThread):
    """Transkrypcja w tle; anulowanie sprawdzane między segmentami."""

    segment_ready = Signal(object)  # SegmentResult
    progressed = Signal(float)  # ułamek nagrania 0.0-1.0
    succeeded = Signal(object)  # TranscriptionResult
    failed = Signal(object)  # AppError
    cancelled = Signal()

    def __init__(
        self,
        audio_path: Path,
        model_dir: Path,
        transcribe_impl: Callable[..., TranscriptionResult] = engine.transcribe,
        parent=None,
        *,
        model: AsrModelInfo | None = None,
        options: DecodingOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self._audio_path = audio_path
        self._model_dir = model_dir
        self._transcribe_impl = transcribe_impl
        self._model = model
        self._options = options
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = self._transcribe_impl(
                self._audio_path,
                self._model_dir,
                should_cancel=lambda: self._cancel_requested,
                on_segment=lambda segment: self.segment_ready.emit(segment),
                on_progress=lambda fraction: self.progressed.emit(fraction),
                **self._extra_arguments(),
            )
        except engine.TranscriptionCancelled:
            self.cancelled.emit()
        except AppError as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)

    def _extra_arguments(self) -> dict[str, object]:
        extra: dict[str, object] = {}
        if self._model is not None:
            extra["model"] = self._model
        if self._options is not None:
            extra["options"] = self._options
        return extra
