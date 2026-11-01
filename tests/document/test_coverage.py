"""Mapa pokrycia transkrypcji: luki bez tekstu i przejścia między nimi."""

from transkryptor.document.anchors import SEGMENT, Anchor
from transkryptor.document.coverage import (
    MIN_GAP_MS,
    gap_target,
    transcription_gaps,
    uncovered,
)
from transkryptor.document.progress import project_stats, stats_rows
from transkryptor.document.project import ProjectState
from transkryptor.document.work_log import WorkLog


def test_uncovered_parts_of_recording() -> None:
    assert uncovered([(1000, 2000), (5000, 8000)], 10_000) == (
        (0, 1000),
        (2000, 5000),
        (8000, 10_000),
    )
    assert uncovered([], 4000) == ((0, 4000),)
    assert uncovered([(0, 12_000)], 10_000) == ()


def test_short_gaps_are_pauses() -> None:
    covered = [(0, 10_000), (11_000, 20_000), (30_000, 40_000)]
    assert transcription_gaps(covered, 40_000) == ((20_000, 30_000),)
    assert MIN_GAP_MS == 3000


def test_silence_is_not_a_gap() -> None:
    covered = [(0, 10_000), (30_000, 40_000)]
    # Cisza w środku luki dzieli ją; krótkie resztki nie są lukami.
    gaps = transcription_gaps(covered, 40_000, silence=[(12_000, 28_000)])
    assert gaps == ()
    gaps = transcription_gaps(covered, 40_000, silence=[(20_000, 28_000)])
    assert gaps == ((10_000, 20_000),)


def test_gap_target_forward_backward_and_wrap() -> None:
    gaps = [(10_000, 15_000), (30_000, 40_000)]
    assert gap_target(gaps, 0) == (10_000, False)
    assert gap_target(gaps, 10_000) == (30_000, False)
    assert gap_target(gaps, 35_000) == (10_000, True)
    assert gap_target(gaps, 35_000, forward=False) == (30_000, False)
    # Tuż za początkiem luki „poprzednia” nie stoi w miejscu.
    assert gap_target(gaps, 30_200, forward=False) == (10_000, False)
    assert gap_target(gaps, 5000, forward=False) == (30_000, True)
    assert gap_target([], 0) is None


def test_stats_report_gaps_like_the_waveform() -> None:
    text = "raz dwa\ntrzy"
    state = ProjectState(
        text=text,
        anchors=(
            Anchor(0, 7, 0, 10_000, SEGMENT),
            Anchor(8, 12, 30_000, 40_000, SEGMENT),
        ),
        work=WorkLog(audio_duration_ms=60_000),
    )
    stats = project_stats(state, "2026-11-01")
    assert stats.gaps == ((10_000, 30_000), (40_000, 60_000))
    assert dict(stats_rows(stats))["Luki w transkrypcji"] == "2 (0:00:40)"
    quiet = project_stats(state, "2026-11-01", silence=[(40_000, 60_000)])
    assert quiet.gaps == ((10_000, 30_000),)
    unknown = project_stats(ProjectState(text="a"), "2026-11-01")
    assert unknown.gaps is None
    assert dict(stats_rows(unknown))["Luki w transkrypcji"] == "-"
