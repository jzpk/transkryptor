"""Spektrogram fragmentu nagrania i cisza w obwiedni (bez Qt)."""

from pathlib import Path

import numpy as np
import pytest

from transkryptor.audio.envelope import Envelope, silent_ranges
from transkryptor.audio.spectrogram import (
    MAX_RANGE_MS,
    NARROWBAND,
    SAMPLE_RATE,
    SpectrogramOptions,
    compute_spectrogram,
    decode_range,
    is_too_long,
    spectrogram_for,
)

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


def column(spectrogram, index: int) -> list[int]:
    """Poziomy jednej kolumny od najniższej częstotliwości."""
    rows = [
        spectrogram.values[row * spectrogram.columns + index]
        for row in range(spectrogram.rows)
    ]
    return rows[::-1]


@pytest.mark.parametrize("hz", [500, 1000, 3000])
def test_tone_peaks_at_its_frequency(hz: int) -> None:
    samples = np.sin(2 * np.pi * hz * np.arange(SAMPLE_RATE) / SAMPLE_RATE)
    spectrogram = compute_spectrogram(samples, SAMPLE_RATE, 2000)
    assert spectrogram.start_ms == 2000
    assert spectrogram.end_ms == 3000
    levels = column(spectrogram, spectrogram.columns // 2)
    peak_hz = levels.index(max(levels)) * spectrogram.max_hz / (spectrogram.rows - 1)
    assert peak_hz == pytest.approx(hz, abs=80)


def test_options_change_range_and_resolution() -> None:
    samples = np.random.default_rng(1).normal(size=SAMPLE_RATE // 2)
    wide = compute_spectrogram(samples, SAMPLE_RATE, 0)
    high = compute_spectrogram(samples, SAMPLE_RATE, 0, SpectrogramOptions(8000))
    assert high.rows > wide.rows
    assert len(wide.values) == wide.rows * wide.columns
    assert max(wide.values) == 255


def test_narrowband_separates_close_harmonics() -> None:
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    samples = np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 1150 * t)

    def dip(options: SpectrogramOptions) -> int:
        spectrogram = compute_spectrogram(samples, SAMPLE_RATE, 0, options)
        levels = column(spectrogram, spectrogram.columns // 2)
        per_row = spectrogram.max_hz / (spectrogram.rows - 1)
        peaks = [levels[round(hz / per_row)] for hz in (1000, 1150)]
        return min(peaks) - levels[round(1075 / per_row)]

    # Okno wąskopasmowe rozdziela tony 150 Hz od siebie, szerokopasmowe - nie.
    assert dip(SpectrogramOptions(5000, NARROWBAND)) > 30
    assert dip(SpectrogramOptions(5000)) < 10


def test_too_long_range_is_refused() -> None:
    assert is_too_long(0, MAX_RANGE_MS + 1)
    assert not is_too_long(0, MAX_RANGE_MS)
    with pytest.raises(ValueError):
        spectrogram_for(SAMPLE_MP3, 0, MAX_RANGE_MS + 1)


def test_decodes_only_the_requested_range() -> None:
    if not SAMPLE_MP3.is_file():
        pytest.skip("brak nagrania testowego")
    samples = decode_range(SAMPLE_MP3, 30_000, 32_000)
    assert len(samples) == pytest.approx(2 * SAMPLE_RATE, abs=SAMPLE_RATE // 50)
    spectrogram = spectrogram_for(SAMPLE_MP3, 30_000, 32_000)
    assert spectrogram.start_ms == 30_000
    assert spectrogram.end_ms == pytest.approx(32_000, abs=20)


def test_decoding_can_be_cancelled() -> None:
    if not SAMPLE_MP3.is_file():
        pytest.skip("brak nagrania testowego")
    with pytest.raises(InterruptedError):
        decode_range(SAMPLE_MP3, 0, 5000, should_cancel=lambda: True)


def test_silent_ranges() -> None:
    peaks = bytes([200] * 50 + [3] * 150 + [180] * 50 + [2] * 20)
    envelope = Envelope(10, peaks)
    # Cisza 1,5 s się liczy, 0,2 s na końcu - nie (za krótka).
    assert silent_ranges(envelope) == ((500, 2000),)
    assert silent_ranges(Envelope(10, bytes(10))) == ((0, 100),)
    assert silent_ranges(Envelope(10, b"")) == ()
