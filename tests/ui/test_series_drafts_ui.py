"""Kolejka szkiców ASR dla serii w oknie: zapis projektów, wznowienie, błędy."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from transkryptor.asr.manager import ModelManager
from transkryptor.asr.models import model_by_key
from transkryptor.asr.results import SegmentResult, TranscriptionResult
from transkryptor.document.project import (
    AsrDraft,
    ProjectState,
    load_project,
    save_project,
)
from transkryptor.errors import AppError
from transkryptor.ui.main_window import MainWindow

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


def _fake_downloader(model, dest: Path, on_progress, should_cancel) -> None:
    for name in (file.name for file in model.files):
        (dest / name).write_bytes(b"fake")


def _transcribe(
    audio_path, model_dir, should_cancel, on_segment, on_progress=None, **_k
):
    if Path(audio_path).name == "w2.mp3":
        raise AppError("uszkodzone nagranie")
    text = f"tak było w {Path(audio_path).stem}"
    segment = SegmentResult(start_s=0.0, end_s=2.0, text=f" {text}", confidence=0.9)
    on_segment(segment)
    if on_progress is not None:
        on_progress(0.5)
    return TranscriptionResult(text=text, language="pl", segments=(segment,))


def _window(
    add_window, tmp_path: Path, names: tuple[str, ...]
) -> tuple[MainWindow, Path]:
    folder = tmp_path / "seria"
    folder.mkdir()
    for name in names:
        shutil.copy(SAMPLE_MP3, folder / name)
    window = add_window(MainWindow())
    store = window.settings_store
    models = tmp_path / "modele"
    current = store.current
    store.save(replace(current, asr=replace(current.asr, models_root=str(models))))
    model = model_by_key(store.current.asr.model_key)
    ModelManager(model, models, _fake_downloader).download()
    window.asr_panel.refresh_model_status()
    window.asr_panel.transcription.set_transcribe_impl(_transcribe)
    window.series.choose_directory = lambda _title, _start: folder
    window.series.folder_dialog()
    drafts = window.series.drafts
    drafts.run_dialog = lambda dialog: dialog.DialogCode.Accepted
    return window, folder


def test_queue_saves_drafts_and_reports_errors(qtbot, add_window, tmp_path) -> None:
    window, folder = _window(add_window, tmp_path, ("w1.mp3", "w2.mp3", "w3.mp3"))
    messages: list[str] = []
    drafts = window.series.drafts
    drafts.show_message = lambda _title, text: messages.append(text)
    assert window.series.drafts_action.isEnabled()
    assert window.series.prepare_drafts()
    assert window.series.busy
    assert not window.editor.isEnabled()
    drafts.wait()
    assert not window.series.busy
    assert window.editor.isEnabled()
    first = load_project(folder / "w1.transkr")
    assert first.asr is not None and "w1" in first.text
    assert first.anchors
    assert not (folder / "w2.transkr").exists()
    assert "w3" in load_project(folder / "w3.transkr").text
    assert "w2.mp3" in messages[-1] and "uszkodzone" in messages[-1]
    # Po kolejce otwarty jest pierwszy szkic.
    assert window.session.project_path == folder / "w1.transkr"


def test_queue_resumes_and_skips_manual_text(qtbot, add_window, tmp_path) -> None:
    window, folder = _window(add_window, tmp_path, ("w1.mp3", "w3.mp3", "w4.mp3"))
    save_project(
        ProjectState(text="szkic", asr=AsrDraft("szkic")), folder / "w1.transkr"
    )
    save_project(ProjectState(text="ręcznie"), folder / "w4.transkr")
    messages: list[str] = []
    drafts = window.series.drafts
    drafts.show_message = lambda _title, text: messages.append(text)
    assert drafts.start(folder)
    drafts.wait()
    assert load_project(folder / "w1.transkr").text == "szkic"
    assert load_project(folder / "w4.transkr").text == "ręcznie"
    assert "w3" in load_project(folder / "w3.transkr").text
    assert "w4.mp3" in messages[-1]
    # Wszystko gotowe - kolejka nie rusza.
    assert not drafts.start(folder)
    assert messages[-1].startswith("Wszystkie nagrania")


def test_cancel_keeps_finished_drafts(qtbot, add_window, tmp_path) -> None:
    window, folder = _window(add_window, tmp_path, ("w1.mp3", "w3.mp3"))
    drafts = window.series.drafts
    drafts.show_message = lambda _title, _text: None
    assert drafts.start(folder)
    drafts.cancel()
    drafts.wait()
    assert not window.series.busy
    assert not (folder / "w3.transkr").exists()
    assert window.editor.isEnabled()
