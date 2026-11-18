"""Backend transkrypcji: kontrakt zgodny z faster-whisper i jego fabryka."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

SAMPLE_RATE = 16_000


class Backend(Protocol):
    """Kontrakt backendu zgodny z ``faster_whisper.WhisperModel.transcribe``.

    Zwraca parę (iterowalne_segmenty, info); segmenty mają ``start``,
    ``end``, ``text`` i ``avg_logprob``, a info opcjonalnie ``language``
    i ``duration``. Niepuste ``initial_prompt`` i ``hotwords`` oraz
    ``word_timestamps=True`` są przekazywane dodatkowo jako argumenty
    nazwane; segmenty mają wtedy ``words`` (``start``, ``end``, ``word``,
    ``probability``).
    """

    def transcribe(
        self, audio: str, /, *, language: str, vad_filter: bool
    ) -> tuple[Iterable[Any], Any]: ...


# Wstrzykiwalna fabryka backendu: (katalog modelu, urządzenie "cuda"/"cpu").
# Testy podstawiają imitację bez modelu.
BackendFactory = Callable[[Path, str], Backend]


def decode_audio(audio: str) -> npt.NDArray[np.float32]:
    """Nagranie jako próbki mono 16 kHz (PyAV/FFmpeg przez faster-whisper)."""
    from faster_whisper.audio import decode_audio as decode

    samples: npt.NDArray[np.float32] = decode(audio, sampling_rate=SAMPLE_RATE)
    return samples


def faster_whisper_backend(model_dir: Path, device: str = "cpu") -> Backend:
    """Ładuje model faster-whisper wyłącznie z lokalnych plików (offline)."""
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_dir),
        device=device,
        compute_type="int8_float16" if device == "cuda" else "int8",
        local_files_only=True,
    )


__all__ = [
    "SAMPLE_RATE",
    "Backend",
    "BackendFactory",
    "decode_audio",
    "faster_whisper_backend",
]
