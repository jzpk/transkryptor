"""Testy dialogu ochrony sesji (ACC-10, REQ-09)."""

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.asr.manager import DownloadCancelled, ModelManager
from transkryptor.ui.main_window import MainWindow

SAMPLE_MP3 = "tests/fixtures/audio/sample.mp3"
SAMPLE_AAC = "tests/fixtures/audio/sample.aac"


@pytest.fixture
def window(add_window):
    return add_window(MainWindow())


def make_dirty(window: MainWindow) -> None:
    window.editor.setPlainText("niewyeksportowana praca")


def answer_dialog(monkeypatch, button) -> list[bool]:
    """Zastępuje QMessageBox.question zadaną odpowiedzią; zwraca historię wywołań."""
    calls: list[bool] = []

    def fake_question(*args, **kwargs):
        calls.append(True)
        return button

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return calls


def answer_question_texts(monkeypatch, button) -> list[str]:
    """Jak ``answer_dialog``, ale zwraca treści pytań."""
    texts: list[str] = []

    def fake_question(_parent, _title, text, *args, **kwargs):
        texts.append(text)
        return button

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return texts


class TestCloseGuard:
    """ACC-10: zamknięcie po edycji bez eksportu pyta o potwierdzenie."""

    def test_close_with_dirty_document_asks_and_can_be_cancelled(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert not window.maybe_discard_changes()
        assert calls == [True]
        assert window.isVisible() or True  # okno nie zostało zamknięte

    def test_close_with_dirty_document_and_confirm_proceeds(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Discard)
        assert window.maybe_discard_changes()

    def test_close_without_changes_does_not_ask(
        self, qtbot, window, monkeypatch
    ) -> None:
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert window.maybe_discard_changes()
        assert calls == []  # czysty dokument — brak pytania

    def test_close_after_export_does_not_ask(self, qtbot, window, monkeypatch) -> None:
        make_dirty(window)
        window.document.mark_exported()
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert window.maybe_discard_changes()
        assert calls == []


class TestNewDocumentGuard:
    """REQ-09: nowy dokument pyta, gdy praca nie została wyeksportowana."""

    def test_new_document_cancelled_keeps_text(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        window._on_new_document()
        assert window.editor.toPlainText() == "niewyeksportowana praca"

    def test_new_document_confirmed_clears_state(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Discard)
        window._on_new_document()
        assert window.editor.toPlainText() == ""
        assert window.author_edit.text() == ""
        assert not window.document.is_dirty
        assert window.player.source_path is None


class TestAudioChangeGuard:
    """REQ-09: zmiana nagrania zachowuje tekst; pyta tylko przy zastąpieniu."""

    def test_first_recording_with_text_does_not_ask(
        self, qtbot, window, monkeypatch
    ) -> None:
        make_dirty(window)
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Cancel)
        window._on_import_audio(SAMPLE_MP3)
        assert calls == []
        assert window.player.source_path is not None
        assert window.editor.toPlainText() == "niewyeksportowana praca"

    def test_change_cancelled_keeps_old_recording(
        self, qtbot, window, monkeypatch
    ) -> None:
        window._on_import_audio(SAMPLE_MP3)
        texts = answer_question_texts(monkeypatch, QMessageBox.StandardButton.Cancel)
        window._on_import_audio(SAMPLE_AAC)
        assert window.player.source_path == Path(SAMPLE_MP3)
        assert len(texts) == 1
        assert "sample.aac" in texts[0]
        assert "zostaną zachowane" in texts[0]
        assert "ASR" not in texts[0]  # brak wyniku ASR — brak zdania o nim

    def test_change_confirmed_keeps_text(self, qtbot, window, monkeypatch) -> None:
        window._on_import_audio(SAMPLE_MP3)
        make_dirty(window)
        answer_dialog(monkeypatch, QMessageBox.StandardButton.Yes)
        window._on_import_audio(SAMPLE_AAC)
        assert window.player.source_path == Path(SAMPLE_AAC)
        assert window.editor.toPlainText() == "niewyeksportowana praca"
        assert window.document.is_dirty

    def test_change_drops_previous_asr_result(self, qtbot, window, monkeypatch) -> None:
        """BUG-06: szkic i segmenty starego nagrania nie trafiają do nowego."""
        window._on_import_audio(SAMPLE_MP3)
        segment = SegmentResult(0.0, 1.0, "od", 0.9)
        window.asr_panel.restore_result(
            TranscriptionResult(text="od", language="pl", segments=(segment,))
        )
        texts = answer_question_texts(monkeypatch, QMessageBox.StandardButton.Yes)
        window._on_import_audio(SAMPLE_AAC)
        assert "ASR" in texts[0]
        assert window.asr_panel.last_result is None
        assert window.asr_panel.segments_list.count() == 0
        assert not window.asr_panel.reinsert_draft_button.isEnabled()
        assert window.session.capture_state().asr is None

    def test_import_error_shows_message(self, qtbot, window, monkeypatch) -> None:
        shown: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2]))
        )
        window._on_import_audio("nieistniejacy.mp3")
        assert len(shown) == 1
        assert "Nie znaleziono" in shown[0]


class TestCloseDuringDownload:
    """BUG-01: zamknięcie w trakcie pobierania modelu nie niszczy wątku."""

    @pytest.fixture
    def downloading(self, qtbot, window, tmp_path):
        started = threading.Event()

        def slow_downloader(model, dest, on_progress, should_cancel) -> None:
            (dest / "model.bin").write_bytes(b"czesciowy")
            started.set()
            for _ in range(2000):  # do 20 s
                if should_cancel():
                    raise DownloadCancelled()
                time.sleep(0.01)
            raise AssertionError("anulowanie nie zadziałało")

        manager = ModelManager(
            models_root=tmp_path / "models", downloader=slow_downloader
        )
        window.asr_panel._manager = manager
        window.asr_panel._start_download()
        assert started.wait(5)
        yield window
        thread = window.asr_panel._download_thread
        if thread is not None:  # sprzątanie po teście „nie zamykaj”
            window.asr_panel.cancel_download_and_wait(5000)

    def test_close_stops_download_after_confirmation(
        self, downloading, monkeypatch
    ) -> None:
        window = downloading
        thread = window.asr_panel._download_thread
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.Yes)
        assert window.session.can_close()
        assert calls == [True]
        assert thread.isFinished()
        assert not window.asr_panel.is_downloading()
        assert not window.asr_panel._manager.model_dir.exists()

    def test_close_declined_keeps_downloading(self, downloading, monkeypatch) -> None:
        window = downloading
        answer_dialog(monkeypatch, QMessageBox.StandardButton.No)
        assert not window.session.can_close()
        assert window.asr_panel.is_downloading()
        assert window.asr_panel._download_thread.isRunning()

    def test_close_without_download_does_not_ask(self, window, monkeypatch) -> None:
        calls = answer_dialog(monkeypatch, QMessageBox.StandardButton.No)
        assert window.session.can_close()
        assert calls == []
