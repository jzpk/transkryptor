"""Kolejka szkiców serii: które nagrania czekają na szkic ASR."""

from __future__ import annotations

from pathlib import Path

from transkryptor.corpus.series import series_recordings
from transkryptor.corpus.series_drafts import draft_queue
from transkryptor.document.project import AsrDraft, ProjectState, save_project


def test_queue_follows_project_files(tmp_path: Path) -> None:
    for name in ("w1.mp3", "w2.mp3", "w3.mp3", "w4.mp3", "w5.mp3"):
        (tmp_path / name).write_bytes(b"audio")
    save_project(ProjectState(asr=AsrDraft(text="szkic")), tmp_path / "w2.transkr")
    save_project(ProjectState(text="ręcznie"), tmp_path / "w3.transkr")
    save_project(ProjectState(metadata={"sygnatura": "W4"}), tmp_path / "w4.transkr")
    (tmp_path / "w5.transkr").write_text("zepsuty", encoding="utf-8")
    queue = draft_queue(series_recordings(tmp_path))
    assert [p.name for p in queue.pending] == ["w1.mp3", "w4.mp3"]
    assert [p.name for p in queue.drafted] == ["w2.mp3"]
    assert [p.name for p in queue.with_text] == ["w3.mp3"]
    assert [(p.name, bool(m)) for p, m in queue.unreadable] == [("w5.mp3", True)]
