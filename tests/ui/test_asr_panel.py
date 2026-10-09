"""Testy panelu ASR: pobieranie, anulowanie, szkic w edytorze, ACC-12, ACC-14–16."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document as DocxDocument
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QMessageBox

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.asr.manager import DownloadCancelled, ModelManager
from transkryptor.asr.models import REQUIRED_FILES, AsrModelInfo
from transkryptor.export.docx_export import export_docx
from transkryptor.i18n import tr
from transkryptor.notation.suggestions import RULES
from transkryptor.ui.asr_panel import (
    APPLIED_MARK,
    PENDING_MARK,
    AsrPanel,
)
from transkryptor.ui.loading_overlay import loading_messages
from transkryptor.ui.main_window import DRAFT_APPEND, DRAFT_REPLACE, MainWindow


def fake_downloader(
    model: AsrModelInfo, dest: Path, on_progress, should_cancel
) -> None:
    for name in REQUIRED_FILES:
        (dest / name).write_bytes(b"fake")
        on_progress(1024, 4096, name)


def fake_transcribe(audio_path, model_dir, should_cancel, on_segment, on_progress=None):
    segment = SimpleNamespace(start_s=0.0, end_s=2.0, text=" są.", confidence=0.9)
    on_segment(segment)
    if on_progress is not None:
        on_progress(0.5)
    return TranscriptionResult(text="są.", language="pl", segments=(segment,))


@pytest.fixture
def manager(tmp_path) -> ModelManager:
    return ModelManager(models_root=tmp_path, downloader=fake_downloader)


def stop_threads(panel: AsrPanel) -> None:
    """Anuluje wątki panelu i czeka na ich zakończenie przed zamknięciem.

    Wołane przez ``before_close_func`` qtbot, czyli przed usunięciem widżetu —
    inaczej działający ``QThread`` emitowałby sygnały do zniszczonego obiektu.
    """
    for thread in (panel._download_thread, panel._transcribe_thread):
        if thread is not None:
            thread.cancel()
            thread.wait(5000)
    # Sygnały zakończenia są w kolejce — bez ich obsługi panel wciąż
    # raportuje trwającą transkrypcję, a okno odmawia zamknięcia.
    QCoreApplication.processEvents()


@pytest.fixture
def panel(qtbot, manager) -> AsrPanel:
    widget = AsrPanel(manager, audio_path_provider=lambda: Path("fake.mp3"))
    qtbot.addWidget(widget, before_close_func=stop_threads)
    return widget


def wait_until(predicate, timeout: float = 10.0, what: str = "warunek") -> None:
    """Przetwarza zdarzenia Qt do spełnienia warunku albo przerywa test.

    Nie używamy ``isVisible()``: w trybie offscreen okno nigdy nie jest
    pokazane, więc ten stan pozostaje fałszywy niezależnie od logiki panelu.
    Czekamy na stan wątku, a widoczność przycisków sprawdzamy przez
    ``isVisibleTo(rodzic)``.
    """
    deadline = time.time() + timeout
    while not predicate():
        if time.time() > deadline:
            raise AssertionError(f"przekroczono czas oczekiwania na: {what}")
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()


def accept_consent(monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )


class TestModelMissingState:
    def test_missing_model_shows_clear_status(self, panel) -> None:
        """Brak modelu to czytelny status i propozycja pobrania, nie awaria."""
        assert panel.model_status_label.text() == tr("asr.model.missing")
        assert panel.download_button.isVisibleTo(panel)
        assert not panel.transcribe_button.isEnabled()

    def test_download_requires_explicit_consent(
        self, qtbot, panel, monkeypatch
    ) -> None:
        """REQ-10/NFR-02: bez zgody użytkownika pobieranie nie startuje."""
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )
        panel.download_button.click()
        assert panel._download_thread is None
        assert panel.model_status_label.text() == tr("asr.model.missing")


class TestDownloadFlow:
    def test_consent_starts_download_and_marks_model_ready(
        self, qtbot, panel, monkeypatch
    ) -> None:
        accept_consent(monkeypatch)
        # Bezpośrednie wywołanie bez wątku — testujemy logikę panelu
        panel._start_download()
        assert panel._download_thread is not None
        wait_until(
            lambda: panel._download_thread is None, what="zakończenie pobierania"
        )
        assert panel.model_status_label.text() == tr("asr.model.ready")
        assert not panel.transcribe_button.isEnabled()  # brak nagrania

    def test_download_error_shows_retryable_message(
        self, qtbot, tmp_path, monkeypatch
    ) -> None:
        def failing_downloader(model, dest, on_progress, should_cancel) -> None:
            raise ConnectionError("brak sieci")

        panel = AsrPanel(
            ModelManager(models_root=tmp_path, downloader=failing_downloader)
        )
        qtbot.addWidget(panel, before_close_func=stop_threads)
        accept_consent(monkeypatch)
        shown: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            staticmethod(lambda _parent, _title, text, *a, **k: shown.append(text)),
        )
        panel.download_button.click()
        wait_until(
            lambda: panel._download_thread is None, what="zakończenie pobierania"
        )
        assert shown and "Sprawdź połączenie" in shown[0]
        assert panel.model_status_label.text() == tr("asr.model.missing")
        assert panel.download_button.isEnabled()  # można ponowić

    def test_download_can_be_cancelled(self, qtbot, tmp_path, monkeypatch) -> None:
        def slow_downloader(model, dest, on_progress, should_cancel) -> None:
            for _ in range(2000):  # do 20 s: czas na kliknięcie anulowania
                if should_cancel():
                    raise DownloadCancelled()
                time.sleep(0.01)
            raise AssertionError("anulowanie nie zadziałało")

        panel = AsrPanel(ModelManager(models_root=tmp_path, downloader=slow_downloader))
        qtbot.addWidget(panel, before_close_func=stop_threads)
        accept_consent(monkeypatch)
        panel.download_button.click()
        wait_until(
            lambda: panel._download_thread is not None
            and panel._download_thread.isRunning(),
            what="start wątku pobierania",
        )
        assert panel.cancel_download_button.isVisibleTo(panel)
        panel.cancel_download_button.click()
        wait_until(lambda: panel._download_thread is None, what="anulowanie pobierania")
        assert panel.model_status_label.text() == "Pobieranie anulowane."
        assert not panel._manager.is_downloaded()


class TestTranscriptionFlow:
    def test_draft_goes_straight_into_empty_editor(
        self, qtbot, window_with_asr
    ) -> None:
        """ACC-14: przy pustym edytorze szkic trafia do niego od razu."""
        window = window_with_asr
        window.editor.clear()
        run_transcription(window)
        assert not hasattr(window.asr_panel, "hypothesis_view")
        assert window.asr_panel.segments_list.count() == 1
        assert window.editor.toPlainText() == "som."
        assert window.asr_panel.suggestions_list.count() == 1

    def test_cancelled_placement_keeps_text_and_allows_reinsert(
        self, qtbot, window_with_asr, no_blocking_dialogs
    ) -> None:
        """ACC-14: przy niepustym edytorze bez wyboru użytkownika nic się nie
        zmienia (REQ-12), a szkic można wstawić później przyciskiem."""
        window = window_with_asr
        run_transcription(window)
        assert any(kind == "exec" for kind, *_ in no_blocking_dialogs)
        assert window.editor.toPlainText() == "ręczny tekst"
        assert window.asr_panel.reinsert_draft_button.isEnabled()

        window._ask_draft_placement = lambda: DRAFT_APPEND
        window.asr_panel.reinsert_draft_button.click()
        assert window.editor.toPlainText() == "ręczny tekst\nsom."

    def test_transcription_can_be_cancelled(
        self, qtbot, window_with_asr, monkeypatch
    ) -> None:
        def slow_transcribe(
            audio_path, model_dir, should_cancel, on_segment, on_progress=None
        ):
            for _ in range(2000):  # do 20 s: czas na kliknięcie anulowania
                if should_cancel():
                    from transkryptor.asr.engine import TranscriptionCancelled

                    raise TranscriptionCancelled()
                time.sleep(0.01)
            raise AssertionError("anulowanie nie zadziałało")

        panel = window_with_asr.asr_panel
        panel._transcribe_impl = slow_transcribe
        panel.transcribe_button.click()
        wait_until(
            lambda: panel._transcribe_thread is not None
            and panel._transcribe_thread.isRunning(),
            what="start wątku transkrypcji",
        )
        assert panel.cancel_transcribe_button.isVisibleTo(panel)
        assert panel._transcribe_thread.isRunning()
        # Panel jest zablokowany nakładką ładowania; anulowanie idzie przez nią.
        window_with_asr.loading_overlay.cancel_button.click()
        wait_until(
            lambda: panel._transcribe_thread is None, what="anulowanie transkrypcji"
        )
        assert (
            window_with_asr.asr_panel.transcribe_status_label.text()
            == "Transkrypcja anulowana."
        )
        # Anulowane zadanie nie dopisuje niczego do dokumentu (REQ-12).
        assert window_with_asr.editor.toPlainText() == "ręczny tekst"

    def test_loading_overlay_locks_window_until_cancelled(
        self, qtbot, window_with_asr
    ) -> None:
        """Na czas transkrypcji okno jest zablokowane nakładką ładowania.

        Praca nadal idzie w wątku w tle (pętla zdarzeń żyje), ale edycja,
        akcje i skróty są wyłączone — aktywne zostaje tylko anulowanie.
        """
        window = window_with_asr
        panel = window.asr_panel
        overlay = window.loading_overlay
        panel._transcribe_impl = _slow_transcribe
        assert not overlay.isVisibleTo(window)

        panel.transcribe_button.click()
        wait_until(
            lambda: panel._transcribe_thread is not None
            and panel._transcribe_thread.isRunning(),
            what="start wątku transkrypcji",
        )
        assert overlay.isVisibleTo(window)
        assert overlay.is_active()
        assert overlay.spinner.is_spinning()
        assert overlay.message_label.text() in loading_messages()
        assert not window.editor.isEnabled()
        assert not panel.isEnabled()
        assert not window.export_action.isEnabled()
        assert not window.superscript_action.isEnabled()
        assert overlay.cancel_button.isEnabled()

        overlay.cancel_button.click()
        wait_until(
            lambda: panel._transcribe_thread is None, what="anulowanie transkrypcji"
        )
        assert not overlay.isVisibleTo(window)
        assert not overlay.spinner.is_spinning()
        assert window.editor.isEnabled()
        assert panel.isEnabled()
        assert window.export_action.isEnabled()
        assert panel.transcribe_status_label.text() == "Transkrypcja anulowana."

    def test_loading_overlay_hides_after_success(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        window.asr_panel.transcribe_button.click()
        wait_until(
            lambda: window.asr_panel._transcribe_thread is None,
            what="zakończenie transkrypcji",
        )
        assert not window.loading_overlay.isVisibleTo(window)
        assert window.editor.isEnabled()

    def test_progress_reaches_overlay_spinner(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        spy = QSignalSpy(window.asr_panel.transcription_progress)
        run_transcription(window)
        assert spy.count() == 1
        assert window.loading_overlay.spinner.percent_text() == "50%"


def run_transcription(window: MainWindow) -> None:
    window.asr_panel.transcribe_button.click()
    wait_until(
        lambda: window.asr_panel._transcribe_thread is None,
        what="zakończenie transkrypcji",
    )


def _slow_transcribe(
    audio_path, model_dir, should_cancel, on_segment, on_progress=None
):
    from transkryptor.asr.engine import TranscriptionCancelled

    for _ in range(2000):  # do 20 s: czas na kliknięcie anulowania
        if should_cancel():
            raise TranscriptionCancelled()
        time.sleep(0.01)
    raise AssertionError("anulowanie nie zadziałało")


@pytest.fixture
def window_with_asr(qtbot, manager):
    """Główne okno z panelem ASR na sztucznym modelu i imitacji transkrypcji."""
    window = MainWindow()
    qtbot.addWidget(window, before_close_func=_release_window)
    window.asr_panel._manager = manager
    window.asr_panel._transcribe_impl = fake_transcribe
    # Panel pyta o ścieżkę nagrania dopiero przy starcie zadania; imitacja
    # transkrypcji jej nie czyta, więc nie uruchamiamy tu Qt Multimedia.
    window.asr_panel._audio_path_provider = lambda: Path("nagranie.mp3")
    manager.download()
    window.asr_panel.refresh_model_status()
    window.asr_panel.set_audio_available(True)
    window.editor.setPlainText("ręczny tekst")
    return window


def _release_window(window: MainWindow) -> None:
    """Zatrzymuje wątki ASR i czyści stan sesji przed zamknięciem okna."""
    stop_threads(window.asr_panel)
    window.document.mark_exported()


def superscripts(window: MainWindow) -> list[tuple[int, int]]:
    window.run_validation_now()
    return window.document.superscript_ranges


class TestDraftPlacement:
    """REQ-14: wstawienie szkicu do edytora bez osobnego okna hipotezy."""

    def test_replace_overwrites_editor(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        window._ask_draft_placement = lambda: DRAFT_REPLACE
        window._on_draft_ready("tak")
        assert window.editor.toPlainText() == "tak"
        window.editor.document().undo()
        assert window.editor.toPlainText() == "ręczny tekst"

    def test_append_adds_new_paragraph_in_plain_format(
        self, qtbot, window_with_asr
    ) -> None:
        """Dopisany szkic nie dziedziczy indeksu górnego z końca tekstu."""
        window = window_with_asr
        cursor = window.editor.textCursor()
        cursor.setPosition(11)
        cursor.setPosition(12, QTextCursor.MoveMode.KeepAnchor)
        window.editor.setTextCursor(cursor)
        window.editor.toggle_superscript()
        window._ask_draft_placement = lambda: DRAFT_APPEND
        window._on_draft_ready("tak")
        assert window.editor.toPlainText() == "ręczny tekst\ntak"
        assert superscripts(window) == [(11, 12)]

    def test_empty_draft_changes_nothing(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        window._on_draft_ready("  ")
        assert window.editor.toPlainText() == "ręczny tekst"


class TestAutomaticRules:
    """REQ-15/ACC-15: reguły wybrane przez autora są stosowane od razu."""

    TEXT = "od są"  # SUG-LAB-U-INIT dla „od”, SUG-NAS-A-FINAL dla „są”

    def _draft(self, window, checked: set[str]) -> None:
        for code, box in window.asr_panel.rule_checkboxes.items():
            box.setChecked(code in checked)
        window.editor.clear()
        window._on_draft_ready(self.TEXT)

    def test_rule_checkboxes_show_confidence(self, qtbot, window_with_asr) -> None:
        boxes = window_with_asr.asr_panel.rule_checkboxes
        assert set(boxes) == {rule.code for rule in RULES}
        assert all(box.isChecked() for box in boxes.values())
        assert "pewność 50%" in boxes["SUG-NAS-A-FINAL"].text()

    def test_all_selected_rules_are_applied(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window, {rule.code for rule in RULES})
        assert window.editor.toPlainText() == "uod som"
        assert superscripts(window) == [(0, 1), (6, 7)]

    def test_only_selected_rules_applied_rest_are_proposals(
        self, qtbot, window_with_asr
    ) -> None:
        window = window_with_asr
        self._draft(window, {"SUG-NAS-A-FINAL"})
        assert window.editor.toPlainText() == "od som"
        labels = [
            window.asr_panel.suggestions_list.item(i).text()
            for i in range(window.asr_panel.suggestions_list.count())
        ]
        assert labels[0].startswith(PENDING_MARK)
        assert labels[1].startswith(APPLIED_MARK)
        assert labels[1] == f"{APPLIED_MARK} są → soᵐ (Nosowość, 50%)"

    def test_undo_restores_raw_draft_then_previous_text(
        self, qtbot, window_with_asr
    ) -> None:
        window = window_with_asr
        window._ask_draft_placement = lambda: DRAFT_REPLACE
        window._on_draft_ready(self.TEXT)
        assert window.editor.toPlainText() == "uod som"
        window.editor.document().undo()
        assert window.editor.toPlainText() == self.TEXT
        window.editor.document().undo()
        assert window.editor.toPlainText() == "ręczny tekst"


class TestReview:
    """REQ-16/ACC-16: podświetlenie i lista automatycznych zmian."""

    def _draft(self, window) -> None:
        window.asr_panel.rule_checkboxes["SUG-LAB-U-INIT"].setChecked(False)
        window.editor.clear()
        window._on_draft_ready("od są")  # → „od som”, „od” jako propozycja

    def test_applied_changes_are_highlighted(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        highlighted = [
            selection.cursor.selectedText()
            for selection in window.editor.extraSelections()
        ]
        assert highlighted == ["om"]  # zmieniona część „są”

    def test_highlight_follows_edits(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        cursor = window.editor.textCursor()
        cursor.setPosition(0)
        cursor.insertText("no ")
        (selection,) = window.editor.extraSelections()
        assert selection.cursor.selectedText() == "om"
        assert selection.cursor.selectionStart() == 7

    def test_activating_item_selects_fragment(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        window.asr_panel.review_item_activated.emit(1)
        assert window.editor.textCursor().selectedText() == "om"

    def test_highlight_is_not_exported(self, qtbot, window_with_asr, tmp_path) -> None:
        window = window_with_asr
        self._draft(window)
        window.run_validation_now()
        export_docx(window.document, tmp_path / "przeglad.docx")
        exported = DocxDocument(tmp_path / "przeglad.docx")
        assert "od som" in [paragraph.text for paragraph in exported.paragraphs]
        body = exported.element.body.xml
        assert "w:highlight" not in body and "w:shd" not in body

    def test_finish_review_clears_highlights_not_text(
        self, qtbot, window_with_asr
    ) -> None:
        window = window_with_asr
        self._draft(window)
        window.asr_panel.finish_review_button.click()
        assert window.editor.extraSelections() == []
        assert window.asr_panel.suggestions_list.count() == 0
        assert window.editor.toPlainText() == "od som"


class TestAcc12ApplyProposal:
    """ACC-12: propozycja zmienia tylko swój fragment i jest cofalna."""

    def _draft(self, window) -> None:
        window.asr_panel.rule_checkboxes["SUG-NAS-A-FINAL"].setChecked(False)
        window.editor.clear()
        window._on_draft_ready("tak są")

    def test_apply_changes_only_its_fragment(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        assert window.editor.toPlainText() == "tak są"
        window.asr_panel.suggestions_list.setCurrentRow(0)
        window.asr_panel.apply_suggestion_button.click()
        assert window.editor.toPlainText() == "tak som"
        assert superscripts(window) == [(6, 7)]
        label = window.asr_panel.suggestions_list.item(0).text()
        assert label.startswith(APPLIED_MARK)
        assert not window.asr_panel.apply_suggestion_button.isEnabled()

    def test_apply_is_undoable(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        window._on_apply_review_item(0)
        assert window.editor.toPlainText() == "tak som"
        window.editor.document().undo()
        assert window.editor.toPlainText() == "tak są"

    def test_stale_fragment_is_not_changed(
        self, qtbot, window_with_asr, no_blocking_dialogs
    ) -> None:
        """Fragment zmieniony od transkrypcji: brak cichej zmiany (REQ-12)."""
        window = window_with_asr
        self._draft(window)
        cursor = window.editor.textCursor()
        cursor.setPosition(5)
        cursor.setPosition(6, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText("ę")
        window._on_apply_review_item(0)
        assert window.editor.toPlainText() == "tak sę"
        assert any(kind == "information" for kind, *_ in no_blocking_dialogs)

    def test_new_document_clears_review(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        window.document.mark_exported()
        window._on_new_document()
        assert window.asr_panel.suggestions_list.count() == 0
        assert window.editor.extraSelections() == []


class TestSegmentSeek:
    """ACC-20: kliknięcie segmentu przewija nagranie przed jego początek."""

    def _add_segment(self, panel: AsrPanel, start_s: float, confidence=0.9):
        segment = SegmentResult(
            start_s=start_s, end_s=start_s + 2, text=" tekst", confidence=confidence
        )
        panel._on_segment_ready(segment)
        return panel.segments_list.item(panel.segments_list.count() - 1)

    def test_click_emits_position_minus_preroll(self, qtbot, panel) -> None:
        item = self._add_segment(panel, 12.3)
        with qtbot.waitSignal(panel.seek_requested) as blocker:
            panel.segments_list.itemClicked.emit(item)
        assert blocker.args == [11_800]

    def test_enter_activates_segment(self, qtbot, panel) -> None:
        item = self._add_segment(panel, 5.0)
        panel.set_segment_preroll_ms(1000)
        with qtbot.waitSignal(panel.seek_requested) as blocker:
            panel.segments_list.itemActivated.emit(item)
        assert blocker.args == [4000]

    def test_position_not_below_zero(self, qtbot, panel) -> None:
        item = self._add_segment(panel, 0.2)
        with qtbot.waitSignal(panel.seek_requested) as blocker:
            panel.segments_list.itemClicked.emit(item)
        assert blocker.args == [0]

    def test_low_confidence_tooltip_invites_listening(self, panel) -> None:
        item = self._add_segment(panel, 1.0, confidence=0.3)
        assert "kliknij, aby odsłuchać" in item.toolTip()

    def test_new_recording_clears_segments(self, panel) -> None:
        self._add_segment(panel, 1.0)
        panel.set_audio_available(True)
        assert panel.segments_list.count() == 0

    def test_window_seeks_and_plays(self, qtbot, add_window) -> None:
        window = add_window(MainWindow())
        window._on_import_audio("tests/fixtures/audio/sample.mp3")
        qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)
        item = self._add_segment(window.asr_panel, 30.0)
        window.asr_panel.segments_list.itemClicked.emit(item)
        qtbot.waitUntil(lambda: window.player.is_playing, timeout=5000)
        qtbot.waitUntil(
            lambda: 29_000 <= window.player.position_ms < 31_000, timeout=5000
        )

    def test_preroll_from_settings(self, add_window) -> None:
        from transkryptor.settings import PlayerSettings, Settings

        window = add_window(MainWindow())
        window.settings_store.save(
            Settings(player=PlayerSettings(segment_preroll_ms=2000))
        )
        assert window.asr_panel._segment_preroll_ms == 2000

    def test_import_other_recording_clears_segments(
        self, qtbot, add_window, monkeypatch
    ) -> None:
        window = add_window(MainWindow())
        window._on_import_audio("tests/fixtures/audio/sample.mp3")
        self._add_segment(window.asr_panel, 3.0)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        window._on_import_audio("tests/fixtures/audio/sample.aac")
        assert window.asr_panel.segments_list.count() == 0


class TestWorkerWiring:
    """PERF-04: domyślnie transkrypcja idzie przez podproces roboczy."""

    def test_default_panel_uses_worker_and_shuts_it_down(self, qtbot, tmp_path) -> None:
        panel = AsrPanel(ModelManager(models_root=tmp_path))
        qtbot.addWidget(panel)
        worker = panel._worker
        assert worker is not None
        assert panel._transcribe_impl == worker.transcribe
        assert worker.ping()
        panel.shutdown()
        assert not worker.is_running()

    def test_injected_implementation_has_no_worker(self, qtbot, tmp_path) -> None:
        panel = AsrPanel(
            ModelManager(models_root=tmp_path),
            transcribe_impl=lambda *a, **k: TranscriptionResult("", "pl"),
        )
        qtbot.addWidget(panel)
        assert panel._worker is None
        panel.shutdown()  # bez procesu — nic do zrobienia
