"""Testy pracy offline po pobraniu modelu (ACC-11, REQ-11, NFR-02).

Trzy poziomy dowodu, od najtańszego do najmocniejszego:

1. kontrakt backendu — model jest ładowany z ``local_files_only=True``,
2. izolacja warstwy Pythona — transkrypcja i sprawdzanie stanu modelu działają
   przy odciętym module ``socket``,
3. przebieg na prawdziwym modelu i prawdziwym nagraniu z odciętą siecią
   (pomijany, gdy model nie został pobrany na tej maszynie).

Dowodem domykającym ACC-11 pozostaje ręczny test z fizycznie odłączonym
interfejsem sieciowym: blokada w Pythonie nie przechwytuje gniazd otwieranych
bezpośrednio z bibliotek natywnych.
"""

from __future__ import annotations

import socket
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from transkryptor.asr import engine
from transkryptor.asr.manager import ModelManager
from transkryptor.asr.models import REQUIRED_FILES

AUDIO_SAMPLE = Path("tests/fixtures/audio/sample.mp3")
EXCERPT_SECONDS = 8
SAMPLE_RATE = 16_000


def make_model_dir(tmp_path: Path) -> Path:
    """Kompletny katalog modelu: znacznik i wszystkie wymagane pliki."""
    model_dir = tmp_path / "medium"
    model_dir.mkdir(parents=True)
    for name in REQUIRED_FILES:
        (model_dir / name).write_bytes(b"fake")
    (model_dir / ".complete").write_text("fake", encoding="utf-8")
    return model_dir


def fake_backend_factory(model_dir: Path) -> engine.Backend:
    """Imitacja faster-whisper: jeden segment, bez modelu i bez sieci."""

    class FakeBackend:
        def transcribe(self, audio_path, language, vad_filter):
            segment = SimpleNamespace(
                start=0.0, end=1.0, text="Hipoteza offline.", avg_logprob=-0.2
            )
            return iter([segment]), SimpleNamespace(language=language)

    return FakeBackend()


@pytest.fixture
def no_network(monkeypatch) -> None:
    """Odcina warstwę sieciową Pythona na czas testu."""

    def deny(*_args, **_kwargs):
        raise AssertionError("test offline: próba użycia sieci")

    class BlockedSocket(socket.socket):
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("test offline: próba otwarcia gniazda")

    monkeypatch.setattr(socket, "socket", BlockedSocket)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")


class TestBackendContract:
    def test_backend_requires_local_files_only(self, monkeypatch) -> None:
        """Model jest ładowany wyłącznie z lokalnego katalogu, na CPU, w int8."""
        captured: dict[str, object] = {}

        class FakeWhisperModel:
            def __init__(self, model_path: str, **kwargs) -> None:
                captured["model_path"] = model_path
                captured.update(kwargs)

        monkeypatch.setitem(
            __import__("sys").modules,
            "faster_whisper",
            SimpleNamespace(WhisperModel=FakeWhisperModel),
        )
        engine._faster_whisper_backend(Path("/katalog/modelu"))

        assert captured["model_path"] == "/katalog/modelu"
        assert captured["local_files_only"] is True
        assert captured["device"] == "cpu"
        assert captured["compute_type"] == "int8"


class TestPythonLayerIsolation:
    def test_transcription_works_without_network(self, tmp_path, no_network) -> None:
        """Silnik nie otwiera gniazd: przebieg kończy się hipotezą."""
        model_dir = make_model_dir(tmp_path)
        audio = tmp_path / "nagranie.mp3"
        audio.write_bytes(b"fake-audio")
        result = engine.transcribe(
            audio, model_dir, backend_factory=fake_backend_factory
        )
        assert result.text == "Hipoteza offline."

    def test_model_state_is_readable_without_network(
        self, tmp_path, no_network
    ) -> None:
        """Stan modelu jest ustalany z dysku, bez odpytywania Hugging Face."""
        manager = ModelManager(models_root=tmp_path)
        assert not manager.is_downloaded()
        assert set(manager.missing_files()) == set(REQUIRED_FILES)

        model_dir = make_model_dir(tmp_path / "gotowy")
        ready = ModelManager(models_root=model_dir.parent)
        assert ready.model_dir == model_dir
        assert ready.is_downloaded()
        assert ready.missing_files() == []


def _excerpt_wav(target: Path) -> float:
    """Zapisuje początkowy fragment próbki testowej jako WAV 16 kHz mono."""
    from faster_whisper.audio import decode_audio

    samples = decode_audio(str(AUDIO_SAMPLE), sampling_rate=SAMPLE_RATE)
    samples = samples[: SAMPLE_RATE * EXCERPT_SECONDS]
    pcm = (samples.clip(-1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return len(samples) / SAMPLE_RATE


@pytest.mark.asr_model
class TestRealModelOffline:
    """ACC-11 na pobranym modelu. Pomijane, gdy modelu nie ma na maszynie."""

    def test_real_transcription_runs_with_network_blocked(
        self, tmp_path, no_network
    ) -> None:
        manager = ModelManager()
        if not manager.is_downloaded():
            pytest.skip(f"model nie jest pobrany w {manager.model_dir}")

        clip = tmp_path / "fragment.wav"
        duration = _excerpt_wav(clip)
        assert duration == pytest.approx(EXCERPT_SECONDS, abs=0.5)

        result = engine.transcribe(clip, manager.model_dir)

        # Próbka to syntetyczny ton, nie mowa: test pilnuje, że prawdziwy
        # model ładuje się i dekoduje nagranie bez sieci, a nie jakości hipotezy.
        assert result.language == "pl"
        for segment in result.segments:
            assert 0.0 <= segment.confidence <= 1.0
            assert segment.end_s >= segment.start_s
