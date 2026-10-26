"""Filtry odsłuchu: przefiltrowana kopia nagrania (FLAC) i jej cache."""

import os

import numpy as np
import pytest

from transkryptor.audio.processing import (
    CHANNEL_BOTH,
    CHANNEL_LEFT,
    CHANNEL_RIGHT,
    AudioFilters,
    cache_path,
    process_audio,
    prune_cache,
)

SAMPLE_MP3 = "tests/fixtures/audio/sample.mp3"
RATE = 16_000


def write_wav(path, left: np.ndarray, right: np.ndarray | None = None) -> None:
    """Zapisuje sygnał float (-1..1) jako WAV mono albo stereo."""
    import av

    channels = [left] if right is None else [left, right]
    samples = (np.stack(channels) * 32767).astype(np.int16)
    layout = "mono" if right is None else "stereo"
    with av.open(str(path), "w", format="wav") as container:
        stream = container.add_stream("pcm_s16le", rate=RATE, layout=layout)
        frame = av.AudioFrame.from_ndarray(
            samples.T.reshape(1, -1), format="s16", layout=layout
        )
        frame.sample_rate = RATE
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def read(path) -> tuple[np.ndarray, int]:
    """Próbki (kanały × próbki, float) i liczba kanałów pliku."""
    import av

    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        channels = len(stream.codec_context.layout.channels)
        resampler = av.AudioResampler(format="fltp", rate=RATE)
        chunks = [
            out.to_ndarray()
            for frame in container.decode(stream)
            for out in resampler.resample(frame)
        ]
        chunks += [out.to_ndarray() for out in resampler.resample(None)]
    return np.concatenate(chunks, axis=1), channels


def tone(seconds: float, amplitude: float, hz: float = 440.0) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


class TestFilters:
    def test_no_filter_is_inactive(self) -> None:
        assert not AudioFilters().active
        assert AudioFilters(normalize=True).active
        assert AudioFilters(highpass=True).active
        assert AudioFilters(channel=CHANNEL_LEFT).active

    def test_channel_choice_is_skipped_for_mono(self) -> None:
        filters = AudioFilters(channel=CHANNEL_RIGHT)
        assert filters.chain(1) == []
        assert filters.chain(2) == [("pan", "mono|c0=FR")]

    def test_key_differs_per_filter_set(self) -> None:
        keys = {
            AudioFilters().key,
            AudioFilters(normalize=True).key,
            AudioFilters(highpass=True).key,
            AudioFilters(channel=CHANNEL_LEFT).key,
            AudioFilters(channel=CHANNEL_RIGHT).key,
        }
        assert len(keys) == 5


class TestProcessAudio:
    def test_keeps_duration_of_real_recording(self, tmp_path) -> None:
        """Czasy kopii pasują do oryginału: kotwice i pętla A-B zostają."""
        import av

        target = tmp_path / "out.flac"
        process_audio(SAMPLE_MP3, target, AudioFilters(normalize=True, highpass=True))
        with av.open(SAMPLE_MP3) as original, av.open(str(target)) as copy:
            assert copy.streams.audio[0].codec_context.name == "flac"
            assert original.duration is not None and copy.duration is not None
            assert abs(original.duration - copy.duration) < 0.2 * av.time_base

    def test_selects_one_channel(self, tmp_path) -> None:
        source = tmp_path / "stereo.wav"
        write_wav(source, tone(1.0, 0.5), np.zeros(RATE, dtype=np.float32))
        left, right = tmp_path / "left.flac", tmp_path / "right.flac"
        process_audio(source, left, AudioFilters(channel=CHANNEL_LEFT))
        process_audio(source, right, AudioFilters(channel=CHANNEL_RIGHT))
        left_samples, left_channels = read(left)
        right_samples, right_channels = read(right)
        assert left_channels == right_channels == 1
        assert rms(left_samples) > 0.3
        assert rms(right_samples) < 0.01

    def test_both_channels_keep_stereo(self, tmp_path) -> None:
        source = tmp_path / "stereo.wav"
        write_wav(source, tone(1.0, 0.5), tone(1.0, 0.5))
        target = tmp_path / "both.flac"
        process_audio(source, target, AudioFilters(channel=CHANNEL_BOTH, highpass=True))
        assert read(target)[1] == 2

    def test_normalize_boosts_quiet_speech(self, tmp_path) -> None:
        source = tmp_path / "quiet.wav"
        write_wav(source, tone(3.0, 0.02, hz=220.0))
        target = tmp_path / "loud.flac"
        process_audio(source, target, AudioFilters(normalize=True))
        original, _ = read(source)
        boosted, _ = read(target)
        # Druga połowa: wzmocnienie narasta powoli.
        half = boosted.shape[1] // 2
        assert rms(boosted[:, half:]) > 3 * rms(original[:, half:])

    def test_highpass_attenuates_rumble(self, tmp_path) -> None:
        source = tmp_path / "rumble.wav"
        write_wav(source, tone(1.0, 0.5, hz=30.0))
        target = tmp_path / "clean.flac"
        process_audio(source, target, AudioFilters(highpass=True))
        assert rms(read(target)[0]) < 0.5 * rms(read(source)[0])

    def test_cancel_leaves_no_file(self, tmp_path) -> None:
        target = tmp_path / "out.flac"
        with pytest.raises(InterruptedError):
            process_audio(
                SAMPLE_MP3, target, AudioFilters(normalize=True), lambda: True
            )
        assert list(tmp_path.iterdir()) == []

    def test_reports_progress(self, tmp_path) -> None:
        progress: list[float] = []
        process_audio(
            SAMPLE_MP3,
            tmp_path / "out.flac",
            AudioFilters(highpass=True),
            on_progress=progress.append,
        )
        assert progress and progress[-1] > 0.9
        assert progress == sorted(progress)

    def test_unreadable_file_raises(self, tmp_path) -> None:
        source = tmp_path / "broken.mp3"
        source.write_bytes(b"to nie jest mp3")
        with pytest.raises(Exception):  # noqa: B017 - błąd PyAV/FFmpeg
            process_audio(source, tmp_path / "out.flac", AudioFilters(highpass=True))
        assert not (tmp_path / "out.flac").exists()


class TestCache:
    def test_path_depends_on_file_and_filters(self, tmp_path) -> None:
        source = tmp_path / "a.wav"
        source.write_bytes(b"1")
        normalize = cache_path(source, AudioFilters(normalize=True), tmp_path)
        highpass = cache_path(source, AudioFilters(highpass=True), tmp_path)
        assert normalize != highpass
        assert normalize == cache_path(source, AudioFilters(normalize=True), tmp_path)
        source.write_bytes(b"22")
        assert cache_path(source, AudioFilters(normalize=True), tmp_path) != normalize

    def test_prune_keeps_recent_copies(self, tmp_path) -> None:
        files = []
        for index in range(5):
            path = tmp_path / f"{index}.flac"
            path.write_bytes(b"x")
            os.utime(path, (1000 + index, 1000 + index))
            files.append(path)
        prune_cache(tmp_path, keep=files[0], limit=2)
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "0.flac",
            "3.flac",
            "4.flac",
        ]
