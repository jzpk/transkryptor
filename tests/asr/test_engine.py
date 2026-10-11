"""Testy silnika transkrypcji: brak modelu, anulowanie, wynik, offline."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from transkryptor.asr import engine
from transkryptor.asr.engine import (
    PROMPT_MAX_CHARS,
    DecodingOptions,
    SegmentResult,
    TranscriptionCancelled,
    TranscriptionError,
    build_hotwords,
    transcribe,
)
from transkryptor.asr.models import DEFAULT_MODEL
from transkryptor.errors import ModelDownloadError


def make_model_dir(tmp_path) -> Path:
    """Tworzy kompletny (znacznik + wymagane pliki) katalog modelu."""
    model_dir = tmp_path / "models" / "medium"
    model_dir.mkdir(parents=True)
    for name in (file.name for file in DEFAULT_MODEL.files):
        (model_dir / name).write_bytes(b"fake")
    (model_dir / ".complete").write_text("fake", encoding="utf-8")
    return model_dir


def make_audio(tmp_path) -> Path:
    audio = tmp_path / "nagranie.mp3"
    audio.write_bytes(b"fake-audio")
    return audio


def fake_backend_factory(model_dir, device="cpu"):
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
            backend_factory=lambda path, device: backend,
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
        result = transcribe(
            audio, model_dir, backend_factory=lambda path, device: backend
        )
        assert backend.loaded_from == model_dir
        assert result.segments

    def test_backend_failure_raises_transcription_error(self, tmp_path) -> None:
        model_dir = make_model_dir(tmp_path)
        audio = make_audio(tmp_path)

        def broken_factory(_path, _device):
            raise RuntimeError("uszkodzony model")

        with pytest.raises(TranscriptionError) as exc_info:
            transcribe(audio, model_dir, backend_factory=broken_factory)
        assert exc_info.value.retry_hint


class RecordingBackend:
    """Backend zapisujący parametry wywołania; opcjonalnie zawodzi na GPU."""

    def __init__(self, device: str, calls: list, fail_on_first: bool = False):
        self.device = device
        self.calls = calls
        self.fail_on_first = fail_on_first

    def transcribe(self, audio_path, **kwargs):
        self.calls.append((self.device, kwargs))
        fail = self.fail_on_first

        def segments():
            if fail:
                raise RuntimeError("Library libcublas.so.12 is not found")
            yield SimpleNamespace(start=0.0, end=1.0, text="Tekst.", avg_logprob=-0.1)

        return segments(), SimpleNamespace(language="pl")


class TestDecodingOptions:
    def test_prompt_and_hotwords_reach_backend(self, tmp_path) -> None:
        """ACC-38: kontekst i słownik trafiają do backendu."""
        calls: list = []
        transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: RecordingBackend(device, calls),
            options=DecodingOptions(
                initial_prompt="Wywiad w Ocieszynie.", hotwords="Ocieszyn Oborniki"
            ),
        )
        [(_, kwargs)] = calls
        assert kwargs["initial_prompt"] == "Wywiad w Ocieszynie."
        assert kwargs["hotwords"] == "Ocieszyn Oborniki"
        assert kwargs["language"] == "pl"

    def test_empty_options_are_not_passed(self, tmp_path) -> None:
        calls: list = []
        transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: RecordingBackend(device, calls),
            options=DecodingOptions(initial_prompt="", hotwords=None),
        )
        [(_, kwargs)] = calls
        assert "initial_prompt" not in kwargs
        assert "hotwords" not in kwargs

    def test_build_hotwords_merges_without_duplicates(self) -> None:
        assert (
            build_hotwords(["Ocieszyn", " Oborniki "], ["oborniki", "", "Rożnowo"])
            == "Ocieszyn Oborniki Rożnowo"
        )
        assert build_hotwords([], [" "]) is None

    def test_build_hotwords_respects_limit(self) -> None:
        words = [f"słowo{index:03d}" for index in range(100)]
        hotwords = build_hotwords(words)
        assert hotwords is not None
        assert len(hotwords) <= PROMPT_MAX_CHARS
        assert hotwords.startswith("słowo000 słowo001")


class TestDevice:
    def test_cpu_when_no_gpu(self, tmp_path) -> None:
        calls: list = []
        result = transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: RecordingBackend(device, calls),
        )
        assert [device for device, _ in calls] == ["cpu"]
        assert result.device == "cpu"
        assert result.device_note is None

    def test_gpu_used_when_available(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)
        calls: list = []
        result = transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: RecordingBackend(device, calls),
        )
        assert result.device == "cuda"
        assert result.text == "Tekst."

    def test_cpu_option_skips_gpu(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)
        calls: list = []
        result = transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: RecordingBackend(device, calls),
            options=DecodingOptions(device="cpu"),
        )
        assert result.device == "cpu"

    def test_falls_back_to_cpu_when_gpu_fails_to_load(
        self, tmp_path, monkeypatch
    ) -> None:
        """ACC-37: błąd ładowania na GPU → CPU z informacją, nie błąd."""
        monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)
        calls: list = []

        def factory(path, device):
            if device == "cuda":
                raise RuntimeError("CUDA driver version is insufficient")
            return RecordingBackend(device, calls)

        result = transcribe(
            make_audio(tmp_path), make_model_dir(tmp_path), backend_factory=factory
        )
        assert result.device == "cpu"
        assert result.device_note == "CUDA driver version is insufficient"
        assert result.text == "Tekst."

    def test_falls_back_when_gpu_fails_on_first_segment(
        self, tmp_path, monkeypatch
    ) -> None:
        """Brak cuBLAS ujawnia się przy pierwszym kodowaniu, nie przy ładowaniu."""
        monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)
        calls: list = []
        result = transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: RecordingBackend(
                device, calls, fail_on_first=device == "cuda"
            ),
        )
        assert [device for device, _ in calls] == ["cuda", "cpu"]
        assert result.device == "cpu"
        assert result.device_note is not None
        assert "libcublas" in result.device_note
        assert [segment.text for segment in result.segments] == ["Tekst."]

    def test_cpu_failure_is_still_an_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)

        def factory(path, device):
            raise RuntimeError(f"zepsuty model ({device})")

        with pytest.raises(TranscriptionError, match="cpu"):
            transcribe(
                make_audio(tmp_path), make_model_dir(tmp_path), backend_factory=factory
            )


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

    AUDIO_SAMPLE = Path("tests/fixtures/audio/sample.mp3")

    def test_mp3_decodes_to_16khz_samples(self) -> None:
        from faster_whisper.audio import decode_audio

        samples = decode_audio(str(self.AUDIO_SAMPLE), sampling_rate=16_000)

        assert len(samples) > 16_000  # ponad sekunda materiału
        assert float(abs(samples).max()) > 0.0  # dekoder zwrócił sygnał
