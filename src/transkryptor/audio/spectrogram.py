"""Spektrogram krótkiego fragmentu nagrania (bez Qt).

Fragment (najwyżej ``MAX_RANGE_MS``) jest dekodowany przez PyAV od miejsca
przewinięcia, po resamplingu do mono ``SAMPLE_RATE`` Hz, a potem liczona
jest krótkoczasowa transformata Fouriera (STFT) z oknem Hanna i wstępnym
podbiciem wysokich tonów (jak w programach fonetycznych). Okno
szerokopasmowe (5 ms) pokazuje formanty, wąskopasmowe (30 ms) - harmoniczne.

Wynik to ``Spectrogram``: poziomy 0-255 (skala dB, ``DYNAMIC_RANGE_DB`` pod
najgłośniejszym punktem fragmentu) w wierszach od najwyższej częstotliwości
- gotowe do narysowania jako obraz z paletą motywu (``ui/spectrogram_view.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# Dłuższe zakresy nie są liczone - spektrogram służy do odsłuchu słów.
MAX_RANGE_MS = 15_000
SAMPLE_RATE = 16_000
WIDEBAND = "wideband"
NARROWBAND = "narrowband"
WINDOWS = (WIDEBAND, NARROWBAND)
WINDOW_MS = {WIDEBAND: 5, NARROWBAND: 30}
MAX_HZ_CHOICES = (5000, 8000)
DYNAMIC_RANGE_DB = 70.0
PRE_EMPHASIS = 0.97
# Docelowa liczba kolumn obrazu (krok czasu zależy od długości fragmentu).
TARGET_COLUMNS = 1200
MIN_HOP_MS = 2.0

CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class SpectrogramOptions:
    max_hz: int = 5000
    window: str = WIDEBAND


DEFAULT_OPTIONS = SpectrogramOptions()


@dataclass(frozen=True)
class Spectrogram:
    """Poziomy 0-255: ``rows`` wierszy (od ``max_hz`` w dół) × ``columns``."""

    start_ms: int
    end_ms: int
    max_hz: int
    rows: int
    columns: int
    values: bytes


def is_too_long(start_ms: int, end_ms: int) -> bool:
    return end_ms - start_ms > MAX_RANGE_MS


def compute_spectrogram(
    samples: np.ndarray,
    rate: int,
    start_ms: int,
    options: SpectrogramOptions = DEFAULT_OPTIONS,
) -> Spectrogram:
    """STFT próbek mono (float) zaczynających się w ``start_ms`` nagrania."""
    import numpy as np

    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    duration_ms = len(samples) * 1000 // rate
    window = max(8, rate * WINDOW_MS.get(options.window, 5) // 1000)
    nfft = 1 << max(9, (window - 1).bit_length())
    hop_ms = max(MIN_HOP_MS, duration_ms / TARGET_COLUMNS)
    hop = max(1, int(rate * hop_ms / 1000))
    if len(samples) < window:
        samples = np.pad(samples, (0, window - len(samples)))
    emphasized = np.append(samples[0], samples[1:] - PRE_EMPHASIS * samples[:-1])
    count = 1 + (len(emphasized) - window) // hop
    indices = np.arange(window)[None, :] + hop * np.arange(count)[:, None]
    frames = emphasized[indices] * np.hanning(window).astype(np.float32)
    magnitude = np.abs(np.fft.rfft(frames, n=nfft, axis=1))
    bins = min(magnitude.shape[1], int(options.max_hz * nfft / rate) + 1)
    levels = 20 * np.log10(magnitude[:, :bins] + 1e-10)
    top = float(levels.max())
    scaled = np.clip((levels - (top - DYNAMIC_RANGE_DB)) / DYNAMIC_RANGE_DB, 0, 1)
    image = np.flipud(scaled.T)  # wiersze: od najwyższej częstotliwości
    values = np.ascontiguousarray(np.rint(image * 255).astype(np.uint8))
    return Spectrogram(
        start_ms=start_ms,
        end_ms=start_ms + duration_ms,
        max_hz=options.max_hz,
        rows=int(values.shape[0]),
        columns=int(values.shape[1]),
        values=values.tobytes(),
    )


def decode_range(
    path: str | Path,
    start_ms: int,
    end_ms: int,
    should_cancel: CancelCheck | None = None,
    rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Próbki mono ``[start_ms, end_ms)`` nagrania (float32, ``rate`` Hz).

    Dekodowanie zaczyna się od przewinięcia do najbliższej ramki przed
    ``start_ms``; ``should_cancel`` przerywa je (``InterruptedError``).
    """
    import av
    import numpy as np

    cancel = should_cancel or (lambda: False)
    chunks: list[np.ndarray] = []
    first_s: float | None = None
    needed = (end_ms / 1000) * rate
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        container.seek(max(0, start_ms - 200) * 1000, any_frame=False)
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        total = 0
        for frame in container.decode(stream):
            if cancel():
                raise InterruptedError(str(path))
            if first_s is None:
                first_s = float(frame.time or 0.0)
            for out in resampler.resample(frame):
                chunk = out.to_ndarray().reshape(-1)
                chunks.append(chunk)
                total += len(chunk)
            if first_s * rate + total >= needed:
                break
    if not chunks or first_s is None:
        return np.zeros(0, dtype=np.float32)
    samples = np.concatenate(chunks)
    begin = max(0, int((start_ms / 1000 - first_s) * rate))
    end = max(begin, int((end_ms / 1000 - first_s) * rate))
    return samples[begin:end]


def spectrogram_for(
    path: str | Path,
    start_ms: int,
    end_ms: int,
    options: SpectrogramOptions = DEFAULT_OPTIONS,
    should_cancel: CancelCheck | None = None,
) -> Spectrogram:
    """Spektrogram fragmentu nagrania; za długi zakres → ``ValueError``."""
    if end_ms <= start_ms or is_too_long(start_ms, end_ms):
        raise ValueError("zakres spektrogramu poza limitem")
    samples = decode_range(path, start_ms, end_ms, should_cancel)
    return compute_spectrogram(samples, SAMPLE_RATE, start_ms, options)
