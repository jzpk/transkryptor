"""Eksport serii: nazwy plików, pomijanie nagrań i archiwum ZIP."""

from __future__ import annotations

import zipfile
from pathlib import Path

from transkryptor.corpus.series import series_recordings
from transkryptor.document.anchors import Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.project import ProjectState, save_project
from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportReport
from transkryptor.export.registry import exporter_by_key, run_export
from transkryptor.export.series_export import (
    SKIP_EMPTY,
    SKIP_NO_PROJECT,
    SKIP_NO_TIMES,
    SKIP_NOT_READY,
    SKIP_UNREADABLE,
    Exported,
    SeriesExportRequest,
    Skipped,
    export_recording,
    output_name,
    planned_names,
    write_zip,
)

TXT = exporter_by_key("txt")


def _series(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("w1.mp3", "w2.mp3", "w3.mp3", "w4.mp3", "w5.mp3"):
        (folder / name).write_bytes(b"audio")
    save_project(ProjectState(text="gotowy"), folder / "w1.transkr")
    comment = Comment("c", 0, 1, "a", "2026-01-01", "do sprawdzenia")
    save_project(
        ProjectState(text="roboczy", comments=(comment,)), folder / "w2.transkr"
    )
    save_project(ProjectState(text="  "), folder / "w3.transkr")
    (folder / "w4.transkr").write_text("zepsuty", encoding="utf-8")
    return series_recordings(folder)


def _writer(exporter=TXT):
    def write(document: ExportDocument, path: Path) -> ExportReport:
        return run_export(exporter, document, path)

    return write


def _export_all(folder: Path, out: Path, request: SeriesExportRequest) -> list:
    recordings = series_recordings(folder)
    out.mkdir(exist_ok=True)
    return [
        export_recording(recording, recordings, request, out, _writer(request.exporter))
        for recording in recordings
    ]


def test_output_name_follows_project(tmp_path: Path) -> None:
    assert output_name(tmp_path / "w1.transkr", TXT, False) == "w1.txt"
    assert output_name(tmp_path / "a.mp3.transkr", TXT, False) == "a.mp3.txt"
    assert output_name(tmp_path / "w1.transkr", TXT, True).startswith("w1")
    assert output_name(tmp_path / "w1.transkr", TXT, True) != "w1.txt"


def test_exports_projects_and_reports_skips(tmp_path: Path) -> None:
    folder = tmp_path / "seria"
    recordings = _series(folder)
    assert planned_names(recordings, TXT, False) == [
        "w1.txt",
        "w2.txt",
        "w3.txt",
        "w4.txt",
    ]
    results = _export_all(folder, tmp_path / "out", SeriesExportRequest(TXT))
    exported = [r.file_name for r in results if isinstance(r, Exported)]
    skipped = {r.recording: r.reason for r in results if isinstance(r, Skipped)}
    assert exported == ["w1.txt", "w2.txt"]
    assert skipped == {
        "w3.mp3": SKIP_EMPTY,
        "w4.mp3": SKIP_UNREADABLE,
        "w5.mp3": SKIP_NO_PROJECT,
    }
    assert "gotowy" in (tmp_path / "out" / "w1.txt").read_text(encoding="utf-8")
    assert all(r.text for r in results if isinstance(r, Skipped))


def test_only_ready_skips_unfinished(tmp_path: Path) -> None:
    folder = tmp_path / "seria"
    _series(folder)
    request = SeriesExportRequest(TXT, only_ready=True)
    results = _export_all(folder, tmp_path / "out", request)
    exported = [r.file_name for r in results if isinstance(r, Exported)]
    assert exported == ["w1.txt"]
    assert any(isinstance(r, Skipped) and r.reason == SKIP_NOT_READY for r in results)


def test_timed_format_needs_time_marks(tmp_path: Path) -> None:
    folder = tmp_path / "seria"
    folder.mkdir()
    for name in ("a1.mp3", "a2.mp3"):
        (folder / name).write_bytes(b"audio")
    save_project(ProjectState(text="bez czasów"), folder / "a1.transkr")
    timed = ProjectState(text="z czasem", anchors=(Anchor(0, 8, 0, 1000),))
    save_project(timed, folder / "a2.transkr")
    srt = exporter_by_key("srt")
    results = _export_all(folder, tmp_path / "out", SeriesExportRequest(srt))
    assert isinstance(results[0], Skipped) and results[0].reason == SKIP_NO_TIMES
    assert isinstance(results[1], Exported) and results[1].file_name == "a2.srt"


def test_write_zip_is_flat(tmp_path: Path) -> None:
    files = []
    for name in ("a.txt", "b.txt"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        files.append(path)
    target = tmp_path / "out" / "seria.zip"
    target.parent.mkdir()
    write_zip(files, target)
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["a.txt", "b.txt"]
    assert [p.name for p in target.parent.iterdir()] == ["seria.zip"]
