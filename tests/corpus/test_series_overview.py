"""Przegląd serii nagrań: stan nagrań z projektów obok nich."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from transkryptor.audio.probe import duration_ms
from transkryptor.corpus.series_overview import (
    DRAFT,
    IN_PROGRESS,
    NO_PROJECT,
    READY,
    UNREADABLE,
    OverviewCancelled,
    ReadinessOptions,
    series_overview,
)
from transkryptor.document.anchors import WORD, Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.diff import Version
from transkryptor.document.project import AsrDraft, ProjectState, save_project
from transkryptor.document.work_log import WorkLog
from transkryptor.settings import Settings

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")
OPTIONS = ReadinessOptions()


def _series(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / name for name in names]
    for path in paths:
        shutil.copy(SAMPLE_MP3, path)
    return paths


def test_duration_from_file_header(tmp_path: Path) -> None:
    (recording,) = _series(tmp_path, "a.mp3")
    assert duration_ms(recording) == pytest.approx(90_000, abs=200)
    broken = tmp_path / "b.mp3"
    broken.write_bytes(b"not audio")
    assert duration_ms(broken) is None


def test_statuses_and_summary(tmp_path: Path) -> None:
    _series(tmp_path, "w1.mp3", "w2.mp3", "w3.mp3", "w4.mp3", "w5.mp3")
    draft = AsrDraft(text="szkic")
    save_project(
        ProjectState(text="szkic", asr=draft, draft_baseline=Version("szkic")),
        tmp_path / "w2.transkr",
    )
    comment = Comment("c1", 0, 3, "a", "2026-01-01", "sprawdzić")
    save_project(
        ProjectState(text="poprawiony szkic", asr=draft, comments=(comment,)),
        tmp_path / "w3.transkr",
    )
    anchor = Anchor(0, 5, 0, 45_000)
    save_project(
        ProjectState(
            text="gotowy tekst",
            anchors=(anchor,),
            work=WorkLog(seconds=600, audio_duration_ms=90_000),
        ),
        tmp_path / "w4.transkr",
    )
    (tmp_path / "w5.transkr").write_text("nie json", encoding="utf-8")
    overview = series_overview(tmp_path, OPTIONS)
    rows = {row.recording.name: row for row in overview.rows}
    assert [row.recording.name for row in overview.rows] == [
        "w1.mp3",
        "w2.mp3",
        "w3.mp3",
        "w4.mp3",
        "w5.mp3",
    ]
    assert rows["w1.mp3"].status == NO_PROJECT
    assert rows["w1.mp3"].duration_ms == pytest.approx(90_000, abs=200)
    assert rows["w2.mp3"].status == DRAFT
    assert rows["w3.mp3"].status == IN_PROGRESS
    assert rows["w3.mp3"].issues == 1
    ready = rows["w4.mp3"]
    assert ready.status == READY
    assert (ready.covered_ms, ready.work_seconds) == (45_000, 600)
    assert ready.coverage == pytest.approx(0.5)
    assert ready.modified is not None
    assert rows["w5.mp3"].status == UNREADABLE and rows["w5.mp3"].error
    assert overview.ready == 1
    assert overview.covered_ms == 45_000
    assert overview.duration_ms == pytest.approx(5 * 90_000, abs=1000)


def test_uncertain_words_and_fields_follow_options(tmp_path: Path) -> None:
    _series(tmp_path, "a1.mp3", "a2.mp3")
    word = Anchor(0, 5, 0, 500, source=WORD, probability=0.1)
    save_project(ProjectState(text="słowo", anchors=(word,)), tmp_path / "a1.transkr")
    assert series_overview(tmp_path, OPTIONS).rows[0].status == READY
    strict = ReadinessOptions.from_settings(Settings())
    assert strict.uncertain_threshold is not None
    row = series_overview(tmp_path, strict).rows[0]
    assert row.status == IN_PROGRESS and row.issues >= 1


def test_cancel(tmp_path: Path) -> None:
    _series(tmp_path, "a1.mp3", "a2.mp3")
    with pytest.raises(OverviewCancelled):
        series_overview(tmp_path, OPTIONS, lambda _done, _total: False)
