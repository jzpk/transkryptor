"""Testy silnika transkrypcji: brak modelu, anulowanie, wynik, offline."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from transkryptor.asr import engine
from transkryptor.asr.engine import (
    PROMPT_MAX_CHARS,
    ChunkedWhisperBackend,
    DecodingOptions,
    SegmentResult,
    TranscriptionCancelled,
    TranscriptionError,
    TranscriptionResult,
    WordResult,
    build_hotwords,
    chunk_bounds,
    draft_text,
    format_timestamp,
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

    def test_word_timestamps_give_words(self, tmp_path) -> None:
        """Faza 11: słowa z czasami i pewnością trafiają do wyniku."""
        calls: list = []

        class WordBackend(RecordingBackend):
            def transcribe(self, audio_path, **kwargs):
                self.calls.append((self.device, kwargs))
                words = [
                    SimpleNamespace(start=0.0, end=0.4, word=" Ala", probability=0.91),
                    SimpleNamespace(start=0.4, end=1.0, word=" ma", probability=0.2),
                ]
                segment = SimpleNamespace(
                    start=0.0, end=1.0, text=" Ala ma", avg_logprob=-0.1, words=words
                )
                return iter([segment]), SimpleNamespace(language="pl")

        result = transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: WordBackend(device, calls),
            options=DecodingOptions(word_timestamps=True),
        )
        [(_, kwargs)] = calls
        assert kwargs["word_timestamps"] is True
        assert result.segments[0].words == (
            WordResult(0.0, 0.4, " Ala", 0.91),
            WordResult(0.4, 1.0, " ma", 0.2),
        )

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
        assert "word_timestamps" not in kwargs

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


class TestOutOfMemory:
    """Brak pamięci dostaje własny komunikat zamiast „pobierz model ponownie”."""

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("mkl_malloc: failed to allocate memory"),
            MemoryError(),
            RuntimeError("std::bad_alloc"),
        ],
    )
    def test_out_of_memory_on_start(self, tmp_path, error) -> None:
        class Backend:
            def transcribe(self, audio_path, language, vad_filter):
                raise error

        with pytest.raises(TranscriptionError) as exc_info:
            transcribe(
                make_audio(tmp_path),
                make_model_dir(tmp_path),
                backend_factory=lambda path, device: Backend(),
            )
        assert "pamięci" in exc_info.value.user_message
        assert "fragmentami" in exc_info.value.retry_hint

    def test_out_of_memory_while_iterating_segments(self, tmp_path) -> None:
        """faster-whisper liczy leniwie: błąd może paść przy kolejnym segmencie."""

        def segments():
            yield SimpleNamespace(start=0.0, end=1.0, text="Raz.", avg_logprob=-0.1)
            raise RuntimeError("mkl_malloc: failed to allocate memory")

        class Backend:
            def transcribe(self, audio_path, language, vad_filter):
                return segments(), SimpleNamespace(language=language)

        with pytest.raises(TranscriptionError, match="pamięci"):
            transcribe(
                make_audio(tmp_path),
                make_model_dir(tmp_path),
                backend_factory=lambda path, device: Backend(),
            )

    def test_other_errors_keep_generic_message(self, tmp_path) -> None:
        def segments():
            raise RuntimeError("uszkodzony plik")
            yield  # pragma: no cover

        class Backend:
            def transcribe(self, audio_path, language, vad_filter):
                return segments(), SimpleNamespace(language=language)

        with pytest.raises(TranscriptionError, match="uszkodzony plik"):
            transcribe(
                make_audio(tmp_path),
                make_model_dir(tmp_path),
                backend_factory=lambda path, device: Backend(),
            )


class ChunkModel:
    """Imitacja WhisperModel dla fragmentów: zapisuje długości i parametry."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, dict]] = []

    def transcribe(self, samples, **kwargs):
        assert isinstance(samples, np.ndarray)  # fragment, nie ścieżka pliku
        self.calls.append((len(samples), kwargs))
        segment = SimpleNamespace(
            start=1.0,
            end=2.0,
            text=f" Fragment {len(self.calls)}.",
            avg_logprob=-0.1,
            words=[
                SimpleNamespace(start=1.5, end=2.0, word=" Fragment", probability=0.5)
            ],
        )
        return iter([segment]), SimpleNamespace(language=kwargs["language"])


class TestChunking:
    """Długie nagranie może trafić do modelu w fragmentach ciętych w ciszy."""

    RATE = 16_000

    def test_short_audio_is_a_single_chunk(self) -> None:
        samples = np.ones(self.RATE * 10, dtype=np.float32)
        assert chunk_bounds(samples, chunk_s=60) == [(0, len(samples))]

    def test_empty_audio_is_a_single_empty_chunk(self) -> None:
        assert chunk_bounds(np.zeros(0, dtype=np.float32)) == [(0, 0)]

    def test_chunks_cover_audio_and_cut_in_silence(self) -> None:
        samples = np.ones(self.RATE * 250, dtype=np.float32)
        # Cisza w oknie poszukiwań przed końcem pierwszego fragmentu (100 s).
        silence = (self.RATE * 92, self.RATE * 93)
        samples[silence[0] : silence[1]] = 0.0
        bounds = chunk_bounds(samples, chunk_s=100, search_s=20)

        assert bounds[0][0] == 0
        assert bounds[-1][1] == len(samples)
        for (_, end), (start, _) in zip(bounds, bounds[1:], strict=False):
            assert end == start  # fragmenty przylegają, nic nie ginie
        for start, end in bounds:
            assert end - start <= self.RATE * 100
        assert silence[0] <= bounds[0][1] < silence[1]

    def test_backend_shifts_segment_times_by_chunk_offset(self) -> None:
        model = ChunkModel()
        samples = np.ones(self.RATE * 25, dtype=np.float32)
        backend = ChunkedWhisperBackend(model, decode=lambda path: samples, chunk_s=10)
        raw_segments, info = backend.transcribe(
            "nagranie.mp3", language="pl", vad_filter=True, hotwords="Ocieszyn"
        )
        assert info.duration == pytest.approx(25.0)
        assert model.calls == []  # model pracuje leniwie, fragment po fragmencie

        segments = list(raw_segments)
        lengths = [length for length, _ in model.calls]
        assert len(segments) == len(lengths) >= 3
        assert sum(lengths) == len(samples)
        assert segments[0].start == pytest.approx(1.0)
        assert segments[1].start == pytest.approx(1.0 + lengths[0] / self.RATE)
        assert segments[1].words[0].start == pytest.approx(1.5 + lengths[0] / self.RATE)
        assert segments[-1].text == f" Fragment {len(lengths)}."
        for _, kwargs in model.calls:  # kontekst i słownik w każdym fragmencie
            assert kwargs == {
                "language": "pl",
                "vad_filter": True,
                "hotwords": "Ocieszyn",
            }

    def test_engine_passes_file_path_by_default(self, tmp_path) -> None:
        """Bez opcji backend dostaje całe nagranie jako ścieżkę (jak dotąd)."""
        seen: list = []

        class Backend:
            def transcribe(self, audio, language, vad_filter):
                seen.append(audio)
                return iter(()), SimpleNamespace(language=language)

        audio = make_audio(tmp_path)
        transcribe(
            audio, make_model_dir(tmp_path), backend_factory=lambda p, d: Backend()
        )
        assert seen == [str(audio)]

    def test_engine_chunks_when_option_enabled(self, tmp_path, monkeypatch) -> None:
        samples = np.ones(self.RATE * 700, dtype=np.float32)
        monkeypatch.setattr(engine, "_decode_audio", lambda path: samples)
        model = ChunkModel()
        result = transcribe(
            make_audio(tmp_path),
            make_model_dir(tmp_path),
            backend_factory=lambda path, device: model,
            options=DecodingOptions(chunked=True),
        )
        assert len(model.calls) == 3  # 700 s w fragmentach po najwyżej 300 s
        assert sum(length for length, _ in model.calls) == len(samples)
        last_offset = sum(length for length, _ in model.calls[:-1]) / self.RATE
        assert result.segments[-1].start_s == pytest.approx(1.0 + last_offset)


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


class TestDraftText:
    """Szkic dzielony na wersy ze znacznikami czasu (najwyżej co 30 s)."""

    @staticmethod
    def result(*spans: tuple[float, float, str]) -> TranscriptionResult:
        segments = tuple(SegmentResult(a, b, text, 0.9) for a, b, text in spans)
        return TranscriptionResult(
            text="".join(s.text for s in segments).strip(),
            language="pl",
            segments=segments,
        )

    def test_lines_cover_at_most_thirty_seconds(self) -> None:
        result = self.result(
            (0.0, 12.0, " tak było"),
            (12.0, 29.5, " i potem"),
            (29.5, 41.0, " we wsi"),
            (41.0, 75.0, " długo"),
            (75.0, 80.0, " koniec"),
        )
        assert draft_text(result).split("\n") == [
            "[00:00] tak było i potem",
            "[00:29] we wsi",
            "[00:41] długo",
            "[01:15] koniec",
        ]

    def test_skips_empty_segments(self) -> None:
        result = self.result((3.0, 4.0, "  "), (4.0, 5.0, " tak"))
        assert draft_text(result) == "[00:04] tak"

    def test_without_segments_returns_hypothesis(self) -> None:
        result = TranscriptionResult(text="stary szkic", language="pl")
        assert draft_text(result) == "stary szkic"

    def test_custom_line_length(self) -> None:
        result = self.result((0.0, 5.0, " a"), (5.0, 11.0, " b"))
        assert draft_text(result, line_seconds=10) == "[00:00] a\n[00:05] b"

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0, "00:00"), (59.9, "00:59"), (754, "12:34"), (3723, "1:02:03")],
    )
    def test_format_timestamp(self, seconds: float, expected: str) -> None:
        assert format_timestamp(seconds) == expected
