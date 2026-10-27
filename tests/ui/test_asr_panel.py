"""Testy panelu ASR: pobieranie, anulowanie, szkic w edytorze, ACC-12, ACC-14-16."""

import time
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QMessageBox

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.asr.manager import DownloadCancelled, ModelManager
from transkryptor.asr.models import DIARIZATION_MODEL, WHISPER_SMALL, AsrModelInfo
from transkryptor.export.docx_export import export_docx
from transkryptor.i18n import tr
from transkryptor.notation.suggestions import default_rules, rule_infos
from transkryptor.settings import AsrSettings, Settings
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.asr_review_section import APPLIED_MARK, PENDING_MARK
from transkryptor.ui.diarization_box import DiarizationBox
from transkryptor.ui.loading_overlay import loading_messages
from transkryptor.ui.main_window import MainWindow
from transkryptor.ui.review import DRAFT_APPEND, DRAFT_REPLACE
from transkryptor.ui.settings_dialog import SettingsDialog


def fake_downloader(
    model: AsrModelInfo, dest: Path, on_progress, should_cancel
) -> None:
    for name in (file.name for file in model.files):
        (dest / name).write_bytes(b"fake")
        on_progress(1024, 4096, name)


def fake_transcribe(
    audio_path, model_dir, should_cancel, on_segment, on_progress=None, **_kwargs
):
    segment = SegmentResult(start_s=0.0, end_s=2.0, text=" są.", confidence=0.9)
    on_segment(segment)
    if on_progress is not None:
        on_progress(0.5)
    return TranscriptionResult(text="są.", language="pl", segments=(segment,))


@pytest.fixture
def manager(tmp_path) -> ModelManager:
    return ModelManager(models_root=tmp_path, downloader=fake_downloader)


def stop_threads(panel: AsrPanel) -> None:
    """Anuluje wątki panelu i czeka na ich zakończenie przed zamknięciem.

    Wołane przez ``before_close_func`` qtbot, czyli przed usunięciem widżetu -
    inaczej działający ``QThread`` emitowałby sygnały do zniszczonego obiektu.
    """
    for thread in (
        panel.models._download_thread,
        panel.transcription._transcribe_thread,
    ):
        if thread is not None:
            thread.cancel()
            thread.wait(5000)
    # Sygnały zakończenia są w kolejce - bez ich obsługi panel wciąż
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
        assert panel.models.model_status_label.text() == tr("asr.model.missing")
        assert panel.models.download_button.isVisibleTo(panel)
        assert not panel.transcription.transcribe_button.isEnabled()

    def test_download_requires_explicit_consent(
        self, qtbot, panel, monkeypatch
    ) -> None:
        """REQ-10/NFR-02: bez zgody użytkownika pobieranie nie startuje."""
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.No,
        )
        panel.models.download_button.click()
        assert panel.models._download_thread is None
        assert panel.models.model_status_label.text() == tr("asr.model.missing")


class TestDownloadFlow:
    def test_consent_starts_download_and_marks_model_ready(
        self, qtbot, panel, monkeypatch
    ) -> None:
        accept_consent(monkeypatch)
        # Bezpośrednie wywołanie bez wątku - testujemy logikę panelu
        panel.models._start_download()
        assert panel.models._download_thread is not None
        wait_until(
            lambda: panel.models._download_thread is None, what="zakończenie pobierania"
        )
        assert panel.models.model_status_label.text() == tr("asr.model.ready")
        assert not panel.transcription.transcribe_button.isEnabled()  # brak nagrania

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
        panel.models.download_button.click()
        wait_until(
            lambda: panel.models._download_thread is None, what="zakończenie pobierania"
        )
        assert shown and "Sprawdź połączenie" in shown[0]
        assert panel.models.model_status_label.text() == tr("asr.model.missing")
        assert panel.models.download_button.isEnabled()  # można ponowić

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
        panel.models.download_button.click()
        wait_until(
            lambda: panel.models._download_thread is not None
            and panel.models._download_thread.isRunning(),
            what="start wątku pobierania",
        )
        assert panel.models.cancel_download_button.isVisibleTo(panel)
        panel.models.cancel_download_button.click()
        wait_until(
            lambda: panel.models._download_thread is None, what="anulowanie pobierania"
        )
        assert panel.models.model_status_label.text() == "Pobieranie anulowane."
        assert not panel.models._manager.is_downloaded()


class TestTranscriptionFlow:
    def test_draft_goes_straight_into_empty_editor(
        self, qtbot, window_with_asr
    ) -> None:
        """ACC-14: przy pustym edytorze szkic trafia do niego od razu."""
        window = window_with_asr
        window.editor.clear()
        run_transcription(window)
        assert not hasattr(window.asr_panel, "hypothesis_view")
        assert window.asr_panel.transcription.segments_list.count() == 1
        assert window.editor.toPlainText() == "[00:00] som."
        assert window.asr_panel.review.suggestions_list.count() == 1

    def test_cancelled_placement_keeps_text_and_allows_reinsert(
        self, qtbot, window_with_asr, no_blocking_dialogs
    ) -> None:
        """ACC-14: przy niepustym edytorze bez wyboru użytkownika nic się nie
        zmienia (REQ-12), a szkic można wstawić później przyciskiem."""
        window = window_with_asr
        run_transcription(window)
        assert any(kind == "exec" for kind, *_ in no_blocking_dialogs)
        assert window.editor.toPlainText() == "ręczny tekst"
        assert window.asr_panel.transcription.reinsert_draft_button.isEnabled()

        window._ask_draft_placement = lambda: DRAFT_APPEND
        window.asr_panel.transcription.reinsert_draft_button.click()
        assert window.editor.toPlainText() == "ręczny tekst\n[00:00] som."

    def test_transcription_can_be_cancelled(
        self, qtbot, window_with_asr, monkeypatch
    ) -> None:
        def slow_transcribe(
            audio_path, model_dir, should_cancel, on_segment, on_progress=None, **_
        ):
            for _step in range(2000):  # do 20 s: czas na kliknięcie anulowania
                if should_cancel():
                    from transkryptor.asr.engine import TranscriptionCancelled

                    raise TranscriptionCancelled()
                time.sleep(0.01)
            raise AssertionError("anulowanie nie zadziałało")

        panel = window_with_asr.asr_panel
        panel.transcription._transcribe_impl = slow_transcribe
        panel.transcription.transcribe_button.click()
        wait_until(
            lambda: panel.transcription._transcribe_thread is not None
            and panel.transcription._transcribe_thread.isRunning(),
            what="start wątku transkrypcji",
        )
        assert panel.transcription.cancel_transcribe_button.isVisibleTo(panel)
        assert panel.transcription._transcribe_thread.isRunning()
        # Panel jest zablokowany nakładką ładowania; anulowanie idzie przez nią.
        window_with_asr.loading_overlay.cancel_button.click()
        wait_until(
            lambda: panel.transcription._transcribe_thread is None,
            what="anulowanie transkrypcji",
        )
        assert (
            window_with_asr.asr_panel.transcription.transcribe_status_label.text()
            == "Transkrypcja anulowana."
        )
        # Anulowane zadanie nie dopisuje niczego do dokumentu (REQ-12).
        assert window_with_asr.editor.toPlainText() == "ręczny tekst"

    def test_loading_overlay_locks_window_until_cancelled(
        self, qtbot, window_with_asr
    ) -> None:
        """Na czas transkrypcji okno jest zablokowane nakładką ładowania.

        Praca nadal idzie w wątku w tle (pętla zdarzeń żyje), ale edycja,
        akcje i skróty są wyłączone - aktywne zostaje tylko anulowanie.
        """
        window = window_with_asr
        panel = window.asr_panel
        overlay = window.loading_overlay
        panel.transcription._transcribe_impl = _slow_transcribe
        assert not overlay.isVisibleTo(window)

        panel.transcription.transcribe_button.click()
        wait_until(
            lambda: panel.transcription._transcribe_thread is not None
            and panel.transcription._transcribe_thread.isRunning(),
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
            lambda: panel.transcription._transcribe_thread is None,
            what="anulowanie transkrypcji",
        )
        assert not overlay.isVisibleTo(window)
        assert not overlay.spinner.is_spinning()
        assert window.editor.isEnabled()
        assert panel.isEnabled()
        assert window.export_action.isEnabled()
        assert (
            panel.transcription.transcribe_status_label.text()
            == "Transkrypcja anulowana."
        )

    def test_loading_overlay_hides_after_success(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        window.asr_panel.transcription.transcribe_button.click()
        wait_until(
            lambda: window.asr_panel.transcription._transcribe_thread is None,
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
    window.asr_panel.transcription.transcribe_button.click()
    wait_until(
        lambda: window.asr_panel.transcription._transcribe_thread is None,
        what="zakończenie transkrypcji",
    )


def _slow_transcribe(
    audio_path, model_dir, should_cancel, on_segment, on_progress=None, **_kwargs
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
    window.asr_panel.models._manager = manager
    window.asr_panel.transcription._transcribe_impl = fake_transcribe
    # Panel pyta o ścieżkę nagrania dopiero przy starcie zadania; imitacja
    # transkrypcji jej nie czyta, więc nie uruchamiamy tu Qt Multimedia.
    window.asr_panel.transcription._audio_path_provider = lambda: Path("nagranie.mp3")
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
        for code, box in window.asr_panel.review.rule_checkboxes.items():
            box.setChecked(code in checked)
        window.editor.clear()
        window._on_draft_ready(self.TEXT)

    def test_rule_checkboxes_show_confidence(self, qtbot, window_with_asr) -> None:
        boxes = window_with_asr.asr_panel.review.rule_checkboxes
        rules = rule_infos(default_rules())
        assert set(boxes) == {rule.code for rule in rules}
        # Zaznaczone są reguły z ``auto_apply``; nowe reguły dają propozycje.
        assert {code for code, box in boxes.items() if box.isChecked()} == {
            rule.code for rule in rules if rule.auto_apply
        }
        assert "pewność 50%" in boxes["SUG-NAS-A-FINAL"].text()

    def test_all_selected_rules_are_applied(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window, {rule.code for rule in rule_infos(default_rules())})
        assert window.editor.toPlainText() == "uod som"
        assert superscripts(window) == [(0, 1), (6, 7)]

    def test_only_selected_rules_applied_rest_are_proposals(
        self, qtbot, window_with_asr
    ) -> None:
        window = window_with_asr
        self._draft(window, {"SUG-NAS-A-FINAL"})
        assert window.editor.toPlainText() == "od som"
        labels = [
            window.asr_panel.review.suggestions_list.item(i).text()
            for i in range(window.asr_panel.review.suggestions_list.count())
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
        window.asr_panel.review.rule_checkboxes["SUG-LAB-U-INIT"].setChecked(False)
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
        window.asr_panel.review.finish_review_button.click()
        assert window.editor.extraSelections() == []
        assert window.asr_panel.review.suggestions_list.count() == 0
        assert window.editor.toPlainText() == "od som"


class TestAcc12ApplyProposal:
    """ACC-12: propozycja zmienia tylko swój fragment i jest cofalna."""

    def _draft(self, window) -> None:
        window.asr_panel.review.rule_checkboxes["SUG-NAS-A-FINAL"].setChecked(False)
        window.editor.clear()
        window._on_draft_ready("tak są")

    def test_apply_changes_only_its_fragment(self, qtbot, window_with_asr) -> None:
        window = window_with_asr
        self._draft(window)
        assert window.editor.toPlainText() == "tak są"
        window.asr_panel.review.suggestions_list.setCurrentRow(0)
        window.asr_panel.review.apply_suggestion_button.click()
        assert window.editor.toPlainText() == "tak som"
        assert superscripts(window) == [(6, 7)]
        label = window.asr_panel.review.suggestions_list.item(0).text()
        assert label.startswith(APPLIED_MARK)
        assert not window.asr_panel.review.apply_suggestion_button.isEnabled()

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
        assert window.asr_panel.review.suggestions_list.count() == 0
        assert window.editor.extraSelections() == []


class TestSegmentSeek:
    """ACC-20: kliknięcie segmentu przewija nagranie przed jego początek."""

    def _add_segment(self, panel: AsrPanel, start_s: float, confidence=0.9):
        segment = SegmentResult(
            start_s=start_s, end_s=start_s + 2, text=" tekst", confidence=confidence
        )
        panel.transcription._on_segment_ready(segment)
        return panel.transcription.segments_list.item(
            panel.transcription.segments_list.count() - 1
        )

    def test_draft_has_timestamped_lines(self, qtbot, panel) -> None:
        result = TranscriptionResult(
            text="tak było we wsi",
            language="pl",
            segments=(
                SegmentResult(0.0, 20.0, " tak było", 0.9),
                SegmentResult(20.0, 45.0, " we wsi", 0.9),
            ),
        )
        panel.transcription._transcribe_thread = None
        with qtbot.waitSignal(panel.draft_ready) as blocker:
            panel.transcription._on_transcribe_succeeded(result)
        assert blocker.args == [result]
        assert panel.transcription._last_draft == "[00:00] tak było\n[00:20] we wsi"

    def test_click_emits_position_minus_preroll(self, qtbot, panel) -> None:
        item = self._add_segment(panel, 12.3)
        with qtbot.waitSignal(panel.seek_requested) as blocker:
            panel.transcription.segments_list.itemClicked.emit(item)
        assert blocker.args == [11_800]

    def test_enter_activates_segment(self, qtbot, panel) -> None:
        item = self._add_segment(panel, 5.0)
        panel.set_segment_preroll_ms(1000)
        with qtbot.waitSignal(panel.seek_requested) as blocker:
            panel.transcription.segments_list.itemActivated.emit(item)
        assert blocker.args == [4000]

    def test_position_not_below_zero(self, qtbot, panel) -> None:
        item = self._add_segment(panel, 0.2)
        with qtbot.waitSignal(panel.seek_requested) as blocker:
            panel.transcription.segments_list.itemClicked.emit(item)
        assert blocker.args == [0]

    def test_low_confidence_tooltip_invites_listening(self, panel) -> None:
        item = self._add_segment(panel, 1.0, confidence=0.3)
        assert "kliknij, aby odsłuchać" in item.toolTip()

    def test_new_recording_clears_segments(self, panel) -> None:
        self._add_segment(panel, 1.0)
        panel.set_audio_available(True)
        assert panel.transcription.segments_list.count() == 0

    def test_window_seeks_and_plays(self, qtbot, add_window) -> None:
        window = add_window(MainWindow())
        window._on_import_audio("tests/fixtures/audio/sample.mp3")
        qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)
        item = self._add_segment(window.asr_panel, 30.0)
        window.asr_panel.transcription.segments_list.itemClicked.emit(item)
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
        assert window.asr_panel.transcription._segment_preroll_ms == 2000

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
        assert window.asr_panel.transcription.segments_list.count() == 0


class TestWorkerWiring:
    """PERF-04: domyślnie transkrypcja idzie przez podproces roboczy."""

    def test_default_panel_uses_worker_and_shuts_it_down(self, qtbot, tmp_path) -> None:
        panel = AsrPanel(ModelManager(models_root=tmp_path))
        qtbot.addWidget(panel)
        worker = panel.transcription._worker
        assert worker is not None
        assert panel.transcription._transcribe_impl == worker.transcribe
        assert worker.ping()
        panel.shutdown()
        assert not worker.is_running()

    def test_injected_implementation_has_no_worker(self, qtbot, tmp_path) -> None:
        panel = AsrPanel(
            ModelManager(models_root=tmp_path),
            transcribe_impl=lambda *a, **k: TranscriptionResult("", "pl"),
        )
        qtbot.addWidget(panel)
        assert panel.transcription._worker is None
        panel.shutdown()  # bez procesu - nic do zrobienia


class TestModelChoice:
    """ACC-35/ACC-36: wybór, pobranie i usunięcie modelu w panelu."""

    def test_combo_lists_registry_with_download_state(self, panel, manager) -> None:
        keys = [
            panel.models.model_combo.itemData(i)
            for i in range(panel.models.model_combo.count())
        ]
        assert keys == ["small", "medium", "large-v3"]
        assert panel.models.model_combo.currentData() == "medium"
        assert all(
            "niepobrany" in panel.models.model_combo.itemText(i)
            for i in range(panel.models.model_combo.count())
        )
        manager.download()
        panel.refresh_model_status()
        index = panel.models.model_combo.findData("medium")
        assert "(pobrany)" in panel.models.model_combo.itemText(index)

    def test_choosing_model_switches_manager_and_emits(
        self, qtbot, panel, manager
    ) -> None:
        manager.download()  # medium pobrany, large-v3 nie
        panel.refresh_model_status()
        with qtbot.waitSignal(panel.model_changed) as blocker:
            panel.models.model_combo.setCurrentIndex(
                panel.models.model_combo.findData("large-v3")
            )
        assert blocker.args == ["large-v3"]
        assert panel.model.key == "large-v3"
        assert panel.model_dir == manager.models_root / "large-v3"
        assert panel.models.model_status_label.text() == tr("asr.model.missing")
        assert panel.models.download_button.isVisibleTo(panel)
        assert "RAM" in panel.models.info_label.text()

    def test_consent_names_selected_model(self, panel) -> None:
        panel.select_model("small")
        text = panel.download_consent_text()
        assert "Systran/faster-whisper-small" in text
        assert "MIT" in text

    def test_select_model_from_settings_does_not_emit(self, qtbot, panel) -> None:
        spy = QSignalSpy(panel.model_changed)
        panel.select_model("small")
        assert panel.models.model_combo.currentData() == "small"
        assert spy.count() == 0

    def test_download_selected_model(self, qtbot, panel, monkeypatch) -> None:
        accept_consent(monkeypatch)
        panel.select_model("small")
        panel.models.download_button.click()
        wait_until(
            lambda: panel.models._download_thread is None, what="zakończenie pobierania"
        )
        assert (panel.model_dir / "model.bin").is_file()
        assert panel.model_dir.name == "small"
        assert panel.models.model_status_label.text() == tr("asr.model.ready")

    def test_delete_requires_confirmation(
        self, panel, manager, no_blocking_dialogs
    ) -> None:
        manager.download()
        panel.refresh_model_status()
        assert panel.models.delete_model_button.isVisibleTo(panel)
        panel.models.delete_model_button.click()  # domyślnie „Nie”
        assert manager.is_downloaded()
        assert no_blocking_dialogs[-1][0] == "question"

    def test_delete_removes_model_and_reports_space(
        self, panel, manager, monkeypatch
    ) -> None:
        small = manager.with_model(WHISPER_SMALL)
        small.download()
        manager.download()
        panel.refresh_model_status()
        accept_consent(monkeypatch)
        panel.models.delete_model_button.click()
        assert not manager.model_dir.exists()
        assert panel.models.model_status_label.text().startswith("Model usunięty")
        assert panel.models.download_button.isVisibleTo(panel)
        assert not panel.models.delete_model_button.isVisibleTo(panel)
        assert small.is_downloaded()  # pozostałe modele zostają (ACC-36)

    def test_model_choice_is_saved_in_settings(
        self, qtbot, window_with_asr, isolated_settings
    ) -> None:
        """ACC-35: wybór modelu przetrwa restart (zapis w ustawieniach)."""
        panel = window_with_asr.asr_panel
        panel.models.model_combo.setCurrentIndex(
            panel.models.model_combo.findData("small")
        )
        assert window_with_asr.settings_store.current.asr.model_key == "small"
        restarted = MainWindow()
        qtbot.addWidget(restarted, before_close_func=_release_window)
        assert restarted.asr_panel.model.key == "small"
        # Zmiana ustawień nie przenosi panelu do domyślnego katalogu modeli.
        assert panel.model_dir.parent == panel.models._manager.models_root

    def test_model_choice_locked_while_transcribing(
        self, qtbot, window_with_asr
    ) -> None:
        panel = window_with_asr.asr_panel
        panel.transcription._transcribe_impl = _slow_transcribe
        panel.transcription.transcribe_button.click()
        wait_until(
            lambda: panel.transcription._transcribe_thread is not None,
            what="start transkrypcji",
        )
        assert not panel.models.model_combo.isEnabled()
        assert not panel.models.delete_model_button.isEnabled()
        panel.cancel_transcription()
        wait_until(
            lambda: panel.transcription._transcribe_thread is None, what="anulowanie"
        )
        assert panel.models.model_combo.isEnabled()

    def test_memory_warning_can_stop_transcription(
        self, qtbot, window_with_asr, monkeypatch, no_blocking_dialogs
    ) -> None:
        monkeypatch.setattr(
            "transkryptor.ui.asr_transcription_section.total_memory_bytes",
            lambda: 1_000_000_000,
        )
        panel = window_with_asr.asr_panel
        panel.transcription.transcribe_button.click()  # pytanie o RAM → „Nie”
        assert panel.transcription._transcribe_thread is None
        kind, title, text = no_blocking_dialogs[-1]
        assert kind == "question" and "RAM" in text


class TestContextAndVocabulary:
    """ACC-38: kontekst nagrania i słownik trafiają do transkrypcji."""

    def test_prompt_length_is_limited(self, panel) -> None:
        from transkryptor.asr.engine import PROMPT_MAX_CHARS

        panel.transcription.context_edit.setText("x" * (PROMPT_MAX_CHARS + 50))
        assert len(panel.transcription.context_edit.text()) == PROMPT_MAX_CHARS
        assert (
            panel.transcription.context_counter.text()
            == f"{PROMPT_MAX_CHARS}/{PROMPT_MAX_CHARS}"
        )

    def test_options_combine_global_and_project_vocabulary(self, panel) -> None:
        from transkryptor.settings import AsrSettings

        panel.set_asr_settings(
            AsrSettings(device="cpu", vocabulary="Oborniki\nOcieszyn")
        )
        panel.transcription.context_edit.setText("Wywiad w Ocieszynie")
        panel.transcription.vocabulary_edit.setPlainText("Rożnowo\nocieszyn")
        options = panel.decoding_options()
        assert options.device == "cpu"
        assert options.initial_prompt == "Wywiad w Ocieszynie"
        assert options.hotwords == "Oborniki Ocieszyn Rożnowo"
        assert "haseł: 2" in panel.transcription.vocabulary_hint.text()

    def test_chunked_option_follows_settings(self, panel) -> None:
        from transkryptor.settings import AsrSettings

        assert panel.decoding_options().chunked is False
        panel.set_asr_settings(AsrSettings(chunked=True))
        assert panel.decoding_options().chunked is True

    def test_empty_context_is_not_sent(self, panel) -> None:
        options = panel.decoding_options()
        assert options.initial_prompt is None
        assert options.hotwords is None

    def test_parameters_reach_transcription(self, qtbot, window_with_asr) -> None:
        calls: list[dict] = []

        def recording(audio_path, model_dir, **kwargs):
            calls.append(kwargs)
            return fake_transcribe(audio_path, model_dir, **kwargs)

        panel = window_with_asr.asr_panel
        panel.transcription._transcribe_impl = recording
        panel.transcription.context_edit.setText("Ocieszyn")
        panel.transcription.vocabulary_edit.setPlainText("Oborniki")
        window_with_asr._ask_draft_placement = lambda: DRAFT_REPLACE
        panel.transcription.transcribe_button.click()
        wait_until(
            lambda: panel.transcription._transcribe_thread is None, what="transkrypcja"
        )
        [kwargs] = calls
        assert kwargs["model"].key == "medium"
        assert kwargs["options"].initial_prompt == "Ocieszyn"
        assert kwargs["options"].hotwords == "Oborniki"

    def test_context_default_from_metadata(self, window_with_asr) -> None:
        window = window_with_asr
        panel = window.asr_panel
        window.metadata_form.set_value("place", "Ocieszyn")
        window.metadata_form.set_value("district", "Oborniki")
        assert panel.transcription.context_edit.text() == "Ocieszyn, Oborniki"
        panel.transcription.context_edit.setText("Mój opis")
        window.metadata_form.set_value("place", "Rożnowo")
        assert (
            panel.transcription.context_edit.text() == "Mój opis"
        )  # wpis użytkownika zostaje

    def test_device_fallback_is_reported(self, qtbot, window_with_asr) -> None:
        """ACC-37: przejście na CPU to informacja, nie błąd."""

        def on_cpu(audio_path, model_dir, **kwargs):
            result = fake_transcribe(audio_path, model_dir, **kwargs)
            return TranscriptionResult(
                text=result.text,
                language="pl",
                segments=result.segments,
                device="cpu",
                device_note="brak libcublas",
            )

        panel = window_with_asr.asr_panel
        panel.transcription._transcribe_impl = on_cpu
        window_with_asr._ask_draft_placement = lambda: DRAFT_REPLACE
        panel.transcription.transcribe_button.click()
        wait_until(
            lambda: panel.transcription._transcribe_thread is None, what="transkrypcja"
        )
        assert "brak libcublas" in panel.transcription.device_label.text()
        assert "CPU" in panel.transcription.device_label.text()


class TestDiarizationOption:
    """Podział na mówców: opcja w ustawieniach, model za zgodą użytkownika."""

    @staticmethod
    def box(qtbot, manager) -> DiarizationBox:
        widget = DiarizationBox(manager)
        qtbot.addWidget(widget, before_close_func=lambda w: w.cancel_and_wait())
        return widget

    def test_option_is_locked_without_model(self, qtbot, manager) -> None:
        box = self.box(qtbot, manager)
        box.set_value(True)
        assert not box.check.isEnabled()
        assert not box.check.isChecked()
        assert box.download_button.isVisibleTo(box)
        # Wybór użytkownika zostaje - zadziała po pobraniu modelu.
        assert box.value() is True

    def test_download_needs_consent(self, qtbot, manager, monkeypatch) -> None:
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )
        box = self.box(qtbot, manager)
        box.download_button.click()
        assert not box.is_downloading()
        assert not box.is_available()

    def test_download_unlocks_and_enables_option(
        self, qtbot, manager, monkeypatch
    ) -> None:
        accept_consent(monkeypatch)
        box = self.box(qtbot, manager)
        box.set_value(False)
        assert "28 MB" in box.consent_text()
        box.download_button.click()
        wait_until(lambda: not box.is_downloading(), what="pobranie modelu mówców")
        assert box.is_available()
        assert box.check.isEnabled() and box.check.isChecked()
        assert box.value() is True
        box.check.setChecked(False)
        assert box.value() is False
        assert box.delete_button.isVisibleTo(box)

    def test_settings_dialog_saves_choice(self, qtbot, manager) -> None:
        dialog = SettingsDialog(Settings(), model_manager=manager)
        qtbot.addWidget(dialog)
        assert dialog.settings().asr.diarize is True
        dialog.diarization_box.set_value(False)
        assert dialog.settings().asr.diarize is False

    def test_settings_dialog_saves_speaker_count(self, qtbot, manager) -> None:
        dialog = SettingsDialog(Settings(), model_manager=manager)
        qtbot.addWidget(dialog)
        assert dialog.settings().asr.diarize_speakers == 2
        dialog.diarization_box.set_speakers(0)
        assert dialog.diarization_box.speakers_combo.currentText() == tr(
            "settings.asr.diarize.speakers.auto"
        )
        assert dialog.settings().asr.diarize_speakers == 0
        dialog.diarization_box.set_speakers(4)
        assert dialog.settings().asr.diarize_speakers == 4

    def test_decoding_options_diarize_only_with_model(self, panel, manager) -> None:
        panel.set_asr_settings(
            AsrSettings(diarize=True, models_root=str(manager.models_root))
        )
        assert not panel.decoding_options().diarize
        diarization = manager.with_model(DIARIZATION_MODEL)
        diarization.download()
        options = panel.decoding_options()
        assert options.diarize
        assert options.diarization_dir == diarization.model_dir
        assert options.speakers == 2
        panel.set_asr_settings(
            AsrSettings(diarize_speakers=0, models_root=str(manager.models_root))
        )
        assert panel.decoding_options().speakers is None
        panel.set_asr_settings(
            AsrSettings(diarize=False, models_root=str(manager.models_root))
        )
        assert not panel.decoding_options().diarize

    def test_panel_speaker_count_shown_only_with_diarization(
        self, panel, manager
    ) -> None:
        root = str(manager.models_root)
        panel.set_asr_settings(AsrSettings(diarize=True, models_root=root))
        assert not panel.transcription.speakers_row.isVisibleTo(panel)  # brak modelu
        manager.with_model(DIARIZATION_MODEL).download()
        panel.refresh_model_status()
        assert panel.transcription.speakers_row.isVisibleTo(panel)
        assert panel.transcription.speakers_combo.currentData() == 2
        panel.set_asr_settings(AsrSettings(diarize=False, models_root=root))
        assert not panel.transcription.speakers_row.isVisibleTo(panel)

    def test_panel_speaker_count_follows_settings_and_emits(
        self, panel, manager
    ) -> None:
        manager.with_model(DIARIZATION_MODEL).download()
        root = str(manager.models_root)
        spy = QSignalSpy(panel.speakers_changed)
        panel.set_asr_settings(AsrSettings(diarize_speakers=5, models_root=root))
        assert panel.transcription.speakers_combo.currentData() == 5
        assert spy.count() == 0  # zmiana z ustawień nie wraca sygnałem
        panel.transcription.speakers_combo.setCurrentIndex(
            panel.transcription.speakers_combo.findData(0)
        )
        assert spy.count() == 1 and spy.at(0) == [0]
        assert panel.decoding_options().speakers is None

    def test_panel_speaker_count_is_saved_in_settings(
        self, window_with_asr, manager, isolated_settings
    ) -> None:
        panel = window_with_asr.asr_panel
        manager.with_model(DIARIZATION_MODEL).download()
        panel.refresh_model_status()
        panel.transcription.speakers_combo.setCurrentIndex(
            panel.transcription.speakers_combo.findData(4)
        )
        assert window_with_asr.settings_store.current.asr.diarize_speakers == 4

    def test_status_shows_speaker_phase(self, panel) -> None:
        panel.transcription._diarizing = True
        panel.transcription._on_transcribe_progress(0.95)
        assert panel.transcription.transcribe_status_label.text() == tr(
            "asr.diarizing.percent", percent=95
        )
