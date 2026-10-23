"""Testy podziału szkicu ASR na mówców (diaryzacja) bez modelu."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from transkryptor.asr import diarization
from transkryptor.asr.diarization import (
    DiarizationCancelled,
    Turn,
    assign_speakers,
    diarize,
)
from transkryptor.asr.engine import (
    DIARIZED_ASR_SHARE,
    DecodingOptions,
    SegmentResult,
    TranscriptionCancelled,
    TranscriptionResult,
    WordResult,
    draft_line_speakers,
    draft_text,
    transcribe,
)
from transkryptor.asr.models import DEFAULT_MODEL, DIARIZATION_MODEL


def words(*spans: tuple[float, float, str]) -> tuple[WordResult, ...]:
    return tuple(WordResult(a, b, text, 0.9) for a, b, text in spans)


def segment(start: float, end: float, *spans: tuple[float, float, str]):
    items = words(*spans)
    return SegmentResult(start, end, "".join(w.text for w in items), 0.8, items)


class TestAssignSpeakers:
    def test_splits_segment_where_speaker_changes(self) -> None:
        source = segment(
            0.0,
            4.2,
            (0.1, 0.5, " Jak"),
            (0.5, 1.0, " było?"),
            (2.0, 2.6, " Dobrze"),
            (2.6, 4.0, " było."),
        )
        turns = [Turn(0.0, 1.2, 7), Turn(1.8, 4.5, 3)]
        first, second = assign_speakers([source], turns)
        assert (first.text, first.speaker) == (" Jak było?", 0)
        assert (second.text, second.speaker) == (" Dobrze było.", 1)
        # Części zachowują granice segmentu na zewnątrz i słów w środku.
        assert (first.start_s, first.end_s) == (0.0, 1.0)
        assert (second.start_s, second.end_s) == (2.0, 4.2)
        assert second.words == source.words[2:]
        assert first.confidence == source.confidence

    def test_speakers_are_numbered_in_order_of_appearance(self) -> None:
        segments = [
            segment(0.0, 1.0, (0.0, 1.0, " a")),
            segment(1.0, 2.0, (1.0, 2.0, " b")),
            segment(2.0, 3.0, (2.0, 3.0, " c")),
        ]
        turns = [Turn(0.0, 1.0, 5), Turn(1.0, 2.0, 2), Turn(2.0, 3.0, 5)]
        assert [s.speaker for s in assign_speakers(segments, turns)] == [0, 1, 0]

    def test_word_takes_speaker_with_largest_overlap(self) -> None:
        source = segment(0.0, 2.0, (0.0, 2.0, " słowo"))
        turns = [Turn(0.0, 0.5, 1), Turn(0.5, 2.0, 2), Turn(1.9, 3.0, 1)]
        [result] = assign_speakers([source], turns)
        # Mówca 2 nakłada się najdłużej, a pierwszy w tekście dostaje numer 0.
        assert result.speaker == 0
        assert result.text == " słowo"

    def test_single_word_of_other_speaker_does_not_split(self) -> None:
        source = segment(
            0.0, 3.0, (0.0, 1.0, " raz"), (1.0, 1.2, " dwa"), (1.2, 3.0, " trzy")
        )
        turns = [Turn(0.0, 1.0, 0), Turn(1.0, 1.2, 1), Turn(1.2, 3.0, 0)]
        [result] = assign_speakers([source], turns)
        assert result.text == " raz dwa trzy"

    def test_segment_without_words_uses_segment_overlap(self) -> None:
        plain = SegmentResult(5.0, 8.0, " bez słów", 0.7)
        turns = [Turn(0.0, 5.5, 1), Turn(5.5, 9.0, 4)]
        [result] = assign_speakers([plain], turns)
        assert (result.text, result.speaker) == (" bez słów", 0)

    def test_gap_between_turns_takes_nearest_speaker(self) -> None:
        source = segment(0.0, 6.0, (0.0, 1.0, " a"), (5.0, 6.0, " b"))
        turns = [Turn(0.0, 1.0, 0), Turn(5.2, 7.0, 1)]
        first, second = assign_speakers([source], turns)
        assert (first.speaker, second.speaker) == (0, 1)

    def test_without_turns_speaker_stays_unknown(self) -> None:
        source = segment(0.0, 1.0, (0.0, 1.0, " a"))
        [result] = assign_speakers([source], [])
        assert result.speaker is None


class FakeDiarizer:
    def __init__(self, items, chunks: int = 4) -> None:
        self.items = items
        self.chunks = chunks
        self.aborted = False

    def process(self, samples, callback=None):
        for done in range(1, self.chunks + 1):
            if callback is not None and callback(done, self.chunks):
                self.aborted = True
                break
        result = SimpleNamespace(sort_by_start_time=lambda: self.items)
        return result


def item(start: float, end: float, speaker: int):
    return SimpleNamespace(start=start, end=end, speaker=speaker)


class TestDiarize:
    def test_returns_sorted_turns_and_reports_progress(self, tmp_path) -> None:
        diarizer = FakeDiarizer([item(3.0, 4.0, 1), item(0.0, 2.0, 0)])
        progress: list[float] = []
        turns = diarize(
            np.zeros(16_000, dtype=np.float32),
            tmp_path,
            on_progress=progress.append,
            factory=lambda path: diarizer,
        )
        assert turns == (Turn(0.0, 2.0, 0), Turn(3.0, 4.0, 1))
        assert progress == [0.25, 0.5, 0.75, 1.0]

    def test_cancel_aborts_processing(self, tmp_path) -> None:
        diarizer = FakeDiarizer([item(0.0, 1.0, 0)])
        with pytest.raises(DiarizationCancelled):
            diarize(
                np.zeros(16_000, dtype=np.float32),
                tmp_path,
                should_cancel=lambda: True,
                factory=lambda path: diarizer,
            )
        assert diarizer.aborted

    def test_speaker_count_reaches_the_factory(self, tmp_path, monkeypatch) -> None:
        calls: list[tuple[Path, int | None]] = []

        def fake(model_dir: Path, speakers: int | None = None) -> FakeDiarizer:
            calls.append((model_dir, speakers))
            return FakeDiarizer([item(0.0, 1.0, 0)])

        monkeypatch.setattr(diarization, "sherpa_diarizer", fake)
        diarize(np.zeros(16_000, dtype=np.float32), tmp_path, speakers=2)
        diarize(np.zeros(16_000, dtype=np.float32), tmp_path)
        assert calls == [(tmp_path, 2), (tmp_path, None)]

    def test_missing_model_file_is_an_error(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            diarize(np.zeros(16_000, dtype=np.float32), tmp_path)


def test_diarization_model_files_are_pinned() -> None:
    names = [file.name for file in DIARIZATION_MODEL.files]
    assert len(set(names)) == len(names)
    for file in DIARIZATION_MODEL.files:
        assert len(file.sha256) == 64 and file.size > 0
    embedding = DIARIZATION_MODEL.files[1]
    assert embedding.repo_id and embedding.revision


# --- integracja z silnikiem ---------------------------------------------------


def make_model_dir(tmp_path) -> Path:
    model_dir = tmp_path / "models" / "medium"
    model_dir.mkdir(parents=True)
    for name in (file.name for file in DEFAULT_MODEL.files):
        (model_dir / name).write_bytes(b"fake")
    (model_dir / ".complete").write_text("fake", encoding="utf-8")
    return model_dir


class WordBackend:
    """Dwa segmenty ze słowami; drugi zawiera zmianę mówcy."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def transcribe(self, audio_path, **kwargs):
        self.kwargs = kwargs

        def word(start, end, text):
            return SimpleNamespace(start=start, end=end, word=text, probability=0.9)

        segments = [
            SimpleNamespace(
                start=0.0,
                end=2.0,
                text=" Gdzie pani mieszka?",
                avg_logprob=-0.1,
                words=[word(0.0, 0.6, " Gdzie"), word(0.6, 2.0, " pani mieszka?")],
            ),
            SimpleNamespace(
                start=2.0,
                end=6.0,
                text=" Tu. A pan?",
                avg_logprob=-0.2,
                words=[word(2.5, 3.0, " Tu."), word(4.5, 6.0, " A pan?")],
            ),
        ]
        return iter(segments), SimpleNamespace(language="pl", duration=6.0)


def run(tmp_path, *, diarizer=None, clip=None, **kwargs) -> TranscriptionResult:
    audio = tmp_path / "nagranie.mp3"
    audio.write_bytes(b"fake-audio")
    backend = kwargs.pop("backend", WordBackend())
    return transcribe(
        audio,
        make_model_dir(tmp_path),
        backend_factory=lambda path, device: backend,
        options=DecodingOptions(
            diarize=True, diarization_dir=tmp_path / "diarization", clip=clip
        ),
        diarizer_factory=lambda path: diarizer
        or FakeDiarizer([item(0.0, 2.2, 3), item(2.2, 4.0, 1), item(4.0, 6.0, 3)]),
        decode=lambda path: np.zeros(16_000 * 6, dtype=np.float32),
        **kwargs,
    )


class TestTranscribeWithDiarization:
    def test_result_is_split_into_speaker_turns(self, tmp_path) -> None:
        result = run(tmp_path)
        assert result.diarized
        assert [(s.text, s.speaker) for s in result.segments] == [
            (" Gdzie pani mieszka?", 0),
            (" Tu.", 1),
            (" A pan?", 0),
        ]
        assert result.text == "Gdzie pani mieszka? Tu. A pan?"

    def test_diarization_requests_word_timestamps(self, tmp_path) -> None:
        backend = WordBackend()
        run(tmp_path, backend=backend)
        assert backend.kwargs["word_timestamps"] is True

    def test_progress_includes_diarization_phase(self, tmp_path) -> None:
        progress: list[float] = []
        run(tmp_path, on_progress=progress.append)
        asr = [p for p in progress if p <= DIARIZED_ASR_SHARE]
        assert asr[-1] == pytest.approx(DIARIZED_ASR_SHARE)
        assert progress[-1] == pytest.approx(1.0)
        assert progress == sorted(progress)

    def test_failure_keeps_draft_without_speakers(self, tmp_path) -> None:
        class Broken:
            def process(self, samples, callback=None):
                raise RuntimeError("onnx failed")

        result = run(tmp_path, diarizer=Broken())
        assert not result.diarized
        assert result.diarization_note == "onnx failed"
        assert len(result.segments) == 2

    def test_cancel_during_diarization(self, tmp_path) -> None:
        calls = {"n": 0}

        def cancel() -> bool:
            calls["n"] += 1
            # Pierwsze sprawdzenia przypadają na transkrypcję.
            return calls["n"] > 4

        with pytest.raises(TranscriptionCancelled):
            run(tmp_path, should_cancel=cancel)

    def test_fragment_is_not_diarized(self, tmp_path) -> None:
        options = DecodingOptions(
            diarize=True, diarization_dir=tmp_path, clip=(1.0, 2.0)
        )
        assert not options.diarizes


class TestDraftWithSpeakers:
    @staticmethod
    def result(*spans: tuple[float, float, str, int | None]) -> TranscriptionResult:
        segments = tuple(
            SegmentResult(a, b, text, 0.9, speaker=speaker)
            for a, b, text, speaker in spans
        )
        return TranscriptionResult(
            text="".join(s.text for s in segments).strip(),
            language="pl",
            segments=segments,
        )

    def test_line_per_speaker_turn_with_time_marker(self) -> None:
        result = self.result(
            (0.0, 3.0, " Jak było?", 0),
            (3.0, 20.0, " Dobrze.", 1),
            (20.0, 70.0, " Bardzo długo opowiadam.", 1),
            (70.0, 72.0, " Aha.", 0),
        )
        # Bez podziału co 30 s: wypowiedź mówcy 1 to jeden wers.
        assert draft_text(result).split("\n") == [
            "[00:00] Jak było?",
            "[00:03] Dobrze. Bardzo długo opowiadam.",
            "[01:10] Aha.",
        ]
        assert draft_line_speakers(result) == [0, 1, 0]

    def test_without_speakers_lines_follow_time(self) -> None:
        result = self.result((0.0, 20.0, " a", None), (20.0, 45.0, " b", None))
        assert draft_text(result) == "[00:00] a\n[00:20] b"
        assert draft_line_speakers(result) == [None, None]
