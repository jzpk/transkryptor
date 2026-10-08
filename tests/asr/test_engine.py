"""Testy silnika transkrypcji: brak modelu, anulowanie, wynik, offline."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from transkryptor.asr.engine import (
    SegmentResult,
    TranscriptionCancelled,
    TranscriptionError,
    transcribe,
)
from transkryptor.asr.models import REQUIRED_FILES
from transkryptor.errors import ModelDownloadError


def make_model_dir(tmp_path) -> Path:
    """Tworzy kompletny (znacznik + wymagane pliki) katalog modelu."""
    model_dir = tmp_path / "models" / "medium"
    model_dir.mkdir(parents=True)
    for name in REQUIRED_FILES:
        (model_dir / name).write_bytes(b"fake")
    (model_dir / ".complete").write_text("fake", encoding="utf-8")
    return model_dir


def make_audio(tmp_path) -> Path:
    audio = tmp_path / "nagranie.mp3"
    audio.write_bytes(b"fake-audio")
    return audio


def fake_backend_factory(model_dir):
    """Imitacja faster-whisper: dwa segmenty, bez sieci i bez modelu."""

    class FakeBackend:
        loaded_from = model_dir  # ślad, że silnik pracuje na lokalnym katalogu

        def transcribe(self, audio_path, language, vad_filter):
            assert language == "pl"
            segments = [
                SimpleNamespace(
                    start=0.0, end=1.5, text="Pierwsze zdanie.", avg_logprob=-0.1
                ),
                SimpleNamespace(
                    start=1.5, end=3.0, text=" Drugie zdanie.", avg_logprob=-0.7
                ),
            ]
            info = SimpleNamespace(language=language)
            return iter(segments), info

    return FakeBackend()


class TestMissingModel:
    def test_missing_model_raises_download_error(self, tmp_path) -> None:
        """Brak modelu to czytelny komunikat ze wskazówką, nie awaria."""
        audio = make_audio(tmp_path)
        with pytest.raises(ModelDownloadError) as exc_info:
            transcribe(audio, tmp_path / "brak-modelu")
        assert "nie został jeszcze pobrany" in exc_info.value.user_message
        assert exc_info.value.retry_hint

    def test_missing_audio_raises_transcription_error(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        with pytest.raises(TranscriptionError, match="Nie znaleziono pliku"):
            transcribe(tmp_path / "nie-ma.mp3", model_dir)


class TestTranscription:
    def test_returns_hypothesis_with_confidence(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)
        seen: list[SegmentResult] = []
        result = transcribe(
            audio,
            model_dir,
            on_segment=seen.append,
            backend_factory=fake_backend_factory,
        )
        assert result.text == "Pierwsze zdanie. Drugie zdanie."
        assert result.language == "pl"
        assert len(result.segments) == 2
        assert len(seen) == 2  # hipoteza i przedziały pewności płyną do UI
        for segment in result.segments:
            assert 0.0 <= segment.confidence <= 1.0
        assert result.segments[0].confidence > result.segments[1].confidence

    def test_reports_progress_relative_to_audio_duration(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)
        backend = fake_backend_factory(model_dir)
        original = backend.transcribe

        def with_duration(*args, **kwargs):
            segments, info = original(*args, **kwargs)
            return segments, SimpleNamespace(language=info.language, duration=6.0)

        backend.transcribe = with_duration
        progress: list[float] = []
        transcribe(
            audio,
            model_dir,
            on_progress=progress.append,
            backend_factory=lambda path: backend,
        )
        assert progress == [0.25, 0.5]

    def test_no_progress_when_duration_unknown(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)
        progress: list[float] = []
        transcribe(
            audio,
            model_dir,
            on_progress=progress.append,
            backend_factory=fake_backend_factory,
        )
        assert progress == []

    def test_model_is_loaded_from_local_directory_only(self, tmp_path) -> None:
        """ACC-11 (strukturalnie): silnik używa wyłącznie lokalnych plików."""
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)
        backend = fake_backend_factory(model_dir)
        result = transcribe(audio, model_dir, backend_factory=lambda path: backend)
        assert backend.loaded_from == model_dir
        assert result.segments

    def test_backend_failure_raises_transcription_error(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)

        def broken_factory(_path):
            raise RuntimeError("uszkodzony model")

        with pytest.raises(TranscriptionError) as exc_info:
            transcribe(audio, model_dir, backend_factory=broken_factory)
        assert exc_info.value.retry_hint


class TestCancellation:
    def test_cancel_before_start(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)
        with pytest.raises(TranscriptionCancelled):
            transcribe(
                audio,
                model_dir,
                should_cancel=lambda: True,
                backend_factory=fake_backend_factory,
            )

    def test_cancel_between_segments_stops_iteration(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)
        calls = {"count": 0}

        def cancel_after_first_segment() -> bool:
            calls["count"] += 1
            return calls["count"] > 2

        with pytest.raises(TranscriptionCancelled):
            transcribe(
                audio,
                model_dir,
                should_cancel=cancel_after_first_segment,
                backend_factory=fake_backend_factory,
            )


class TestAudioDecodingContract:
    """Dekodowanie nagrania przez stos faster-whisper/PyAV musi działać.

    Silnik przekazuje backendowi ścieżkę pliku, a faster-whisper dekoduje go
    przez PyAV. Ten test pilnuje tej granicy wersji: faster-whisper woła
    ``av.open(..., metadata_errors=...)``, a PyAV usunął ten argument
    w 19.0.0 — bez ograniczenia zależności każda transkrypcja pliku
    kończyłaby się ``TypeError`` dopiero u użytkownika.
    """

    AUDIO_SAMPLE = Path("test/JaE_1979_przesądy.mp3")

    def test_mp3_decodes_to_16khz_samples(self) -> None:
        if not self.AUDIO_SAMPLE.is_file():
            pytest.skip(f"brak nagrania testowego {self.AUDIO_SAMPLE}")
        from faster_whisper.audio import decode_audio

        samples = decode_audio(str(self.AUDIO_SAMPLE), sampling_rate=16_000)

        assert len(samples) > 16_000  # ponad sekunda materiału
        assert float(abs(samples).max()) > 0.0  # dekoder zwrócił sygnał
