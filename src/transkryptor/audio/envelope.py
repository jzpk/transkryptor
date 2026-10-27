"""Obwiednia nagrania dla fali dźwiękowej (faza 11, propozycja 6; bez Qt).

Obwiednia to wartość szczytowa amplitudy co ``STEP_MS`` milisekund,
zapisana jako bajty 0-255 (godzina nagrania ≈ 360 KB). Nagranie dekoduje
PyAV (ta sama zależność co ASR) strumieniowo, po resamplingu do mono
``ENVELOPE_RATE`` Hz - pamięć nie rośnie z długością nagrania.

Wynik jest zapisywany w katalogu pamięci podręcznej użytkownika pod sumą
SHA-256 nagrania; ponowne otwarcie tego samego nagrania nie dekoduje go
od nowa. Uszkodzony albo niezgodny plik cache jest pomijany.
"""

from __future__ import annotations

import struct
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from transkryptor.paths import user_cache_dir

STEP_MS = 10
ENVELOPE_RATE = 8_000
_MAGIC = b"TKENV"
_VERSION = 1
_HEADER = struct.Struct("<5sBHI")  # magia, wersja, krok ms, liczba wartości

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[float], None]


@dataclass(frozen=True)
class Envelope:
    """Szczyty amplitudy (0-255) co ``step_ms`` milisekund."""

    step_ms: int
    peaks: bytes

    @property
    def duration_ms(self) -> int:
        return len(self.peaks) * self.step_ms


def waveform_cache_dir() -> Path:
    return user_cache_dir() / "waveforms"


def compute_envelope(
    path: str | Path,
    should_cancel: CancelCheck | None = None,
    on_progress: ProgressCallback | None = None,
    step_ms: int = STEP_MS,
) -> Envelope:
    """Dekoduje nagranie i zwraca obwiednię.

    ``should_cancel`` przerywa dekodowanie (``InterruptedError``); błąd
    odczytu pliku - ``OSError`` albo wyjątek PyAV (``av.FFmpegError``).
    """
    import av
    import numpy as np

    cancel = should_cancel or (lambda: False)
    hop = ENVELOPE_RATE * step_ms // 1000
    peaks = bytearray()
    pending = np.zeros(0, dtype=np.float32)

    def consume(samples: np.ndarray, final: bool = False) -> np.ndarray:
        full = len(samples) // hop * hop
        if full:
            blocks = np.abs(samples[:full]).reshape(-1, hop).max(axis=1)
            peaks.extend(_quantize(blocks))
        rest = samples[full:]
        if final and len(rest):
            peaks.extend(_quantize(np.abs(rest).max(keepdims=True)))
            return rest[:0]
        return rest

    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        duration_s = (
            container.duration / av.time_base if container.duration else 0.0
        ) or float((stream.duration or 0) * (stream.time_base or 0))
        resampler = av.AudioResampler(format="flt", layout="mono", rate=ENVELOPE_RATE)
        for frame in container.decode(stream):
            if cancel():
                raise InterruptedError(str(path))
            for out in resampler.resample(frame):
                pending = consume(
                    np.concatenate([pending, out.to_ndarray().reshape(-1)])
                )
            if on_progress is not None and duration_s > 0 and frame.time is not None:
                on_progress(min(1.0, float(frame.time) / duration_s))
        for out in resampler.resample(None):
            pending = consume(np.concatenate([pending, out.to_ndarray().reshape(-1)]))
        consume(pending, final=True)
    return Envelope(step_ms, bytes(peaks))


def _quantize(values: object) -> bytes:
    import numpy as np

    scaled = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0) * 255
    return bytes(np.rint(scaled).astype(np.uint8))


def _cache_path(sha256: str, directory: Path | None) -> Path:
    return (directory or waveform_cache_dir()) / f"{sha256}.env"


def load_cached(sha256: str, directory: Path | None = None) -> Envelope | None:
    """Obwiednia z pamięci podręcznej albo None (brak, uszkodzona, inna wersja)."""
    if not sha256:
        return None
    try:
        raw = _cache_path(sha256, directory).read_bytes()
    except OSError:
        return None
    if len(raw) < _HEADER.size:
        return None
    magic, version, step_ms, count = _HEADER.unpack_from(raw)
    peaks = raw[_HEADER.size :]
    if magic != _MAGIC or version != _VERSION or step_ms <= 0 or len(peaks) != count:
        return None
    return Envelope(step_ms, peaks)


def save_cached(sha256: str, envelope: Envelope, directory: Path | None = None) -> bool:
    """Zapisuje obwiednię atomowo; błąd zapisu nie przerywa pracy (False)."""
    if not sha256:
        return False
    target = _cache_path(sha256, directory)
    payload = (
        _HEADER.pack(_MAGIC, _VERSION, envelope.step_ms, len(envelope.peaks))
        + envelope.peaks
    )
    temp_name: str | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
        Path(temp_name).replace(target)
        temp_name = None
    except OSError:
        return False
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    return True
