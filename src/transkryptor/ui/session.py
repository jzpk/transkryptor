"""Stan sesji: dokument, projekt, nagranie i ochrona pracy.

``SessionController`` jest właścicielem modelu ``Document`` bieżącej sesji
i pliku projektu (``.transkr``). Pilnuje, by praca nie zginęła bez
potwierdzenia (REQ-09, ACC-10, ACC-31) — przy nowym dokumencie, otwarciu
projektu, imporcie DOCX i zamknięciu: dokument z plikiem projektu pyta
o niezapisane zmiany, dokument bez pliku — o niewyeksportowane. Okno pytania
ma opcję „Zapisz”. Zmiana nagrania nie porzuca tekstu, więc ma osobne
pytanie: tylko gdy zastępuje inne nagranie albo usuwa wynik ASR.

Sumę SHA-256 nagrania liczy wątek w tle (``ui/audio_hash.py``); zapis
projektu czeka na nią, autozapis — nie (pusta suma = brak weryfikacji).

Kontroler zapisuje i otwiera projekty (ACC-28, ACC-29), importuje DOCX
(ACC-33) i odzyskuje pracę z autozapisu (ACC-30, ``ui/autosave.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QDate, QObject
from PySide6.QtWidgets import QDateEdit, QFileDialog, QLineEdit, QMessageBox, QWidget

from transkryptor.asr.engine import SegmentResult, TranscriptionResult
from transkryptor.audio.player import AudioPlayer
from transkryptor.audio.player import file_dialog_filter as audio_filter
from transkryptor.document.metadata import (
    SIGNATURE,
    MetadataField,
    normalized,
    signature_from_audio,
)
from transkryptor.document.model import Document
from transkryptor.document.project import (
    PROJECT_SUFFIX,
    AsrDraft,
    AsrSegment,
    AudioRef,
    ProjectState,
    file_dialog_filter,
    file_sha256,
    load_project,
    resolve_audio,
    save_project,
)
from transkryptor.errors import AppError
from transkryptor.export.docx_import import import_docx
from transkryptor.i18n import tr
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.audio_hash import HashFunction, HashThread, wait_for
from transkryptor.ui.autosave import AutosaveController, RecoveryDialog, find_orphans
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.messages import show_error
from transkryptor.ui.metadata_form import MetadataForm
from transkryptor.ui.player_bar import PlayerBar
from transkryptor.ui.review import ReviewController
from transkryptor.ui.settings_store import SettingsStore

DATE_FORMAT = "yyyy-MM-dd"
# Ile zamknięcie okna czeka na przerwanie pobierania modelu.
DOWNLOAD_SHUTDOWN_WAIT_MS = 5000


class SessionController(QObject):
    """Dokument sesji, plik projektu i operacje, które mogą porzucić pracę."""

    def __init__(
        self,
        dialog_parent: QWidget,
        editor: TranscriptionEditor,
        player: AudioPlayer,
        player_bar: PlayerBar,
        asr_panel: AsrPanel,
        review: ReviewController,
        author_edit: QLineEdit,
        date_edit: QDateEdit,
        metadata_form: MetadataForm,
        settings_store: SettingsStore,
        on_reset: Callable[[], None],
        on_state_changed: Callable[[], None],
    ) -> None:
        super().__init__(dialog_parent)
        self._document = Document()
        # Edytor zmienił się od ostatniej synchronizacji z ``_document``.
        self._editor_pending = False
        self.project_path: Path | None = None
        self._audio: AudioRef | None = None
        self._parent = dialog_parent
        self._editor = editor
        self._player = player
        self._player_bar = player_bar
        self._asr_panel = asr_panel
        self._review = review
        self._author_edit = author_edit
        self._date_edit = date_edit
        self._metadata_form = metadata_form
        self._settings_store = settings_store
        self._on_reset = on_reset
        self._on_state_changed = on_state_changed
        # Liczenie sumy nagrania w tle; testy podstawiają wolną imitację.
        self.hash_impl: HashFunction = file_sha256
        self._hash_thread: HashThread | None = None
        self._hash_threads: set[HashThread] = set()
        self.autosave = AutosaveController(
            self.capture_state, lambda: self.document, self
        )

    @property
    def document(self) -> Document:
        """Dokument sesji zsynchronizowany z edytorem.

        Edycja tylko zaznacza zmianę (:meth:`mark_editor_changed`); pełna
        synchronizacja odbywa się tu, przy pierwszym odczycie — zapis,
        eksport, autozapis i walidacja zawsze widzą bieżący tekst.
        """
        self.flush_editor()
        return self._document

    @document.setter
    def document(self, document: Document) -> None:
        self._document = document
        # Nowy dokument przychodzi razem z treścią edytora.
        self._editor_pending = False

    def mark_editor_changed(self) -> None:
        """Tani znacznik zmiany w edytorze (wołany przy każdym klawiszu)."""
        self._editor_pending = True

    def flush_editor(self) -> bool:
        """Przepisuje oczekujące zmiany edytora do dokumentu."""
        if not self._editor_pending:
            return False
        self._editor_pending = False
        return self._editor.sync_to_document(self._document)

    @property
    def project_name(self) -> str | None:
        return self.project_path.name if self.project_path is not None else None

    @property
    def has_unsaved_work(self) -> bool:
        """Czy porzucenie dokumentu wymaga pytania (ACC-10, ACC-31)."""
        if self.project_path is not None:
            return self.document.is_unsaved
        return self.document.is_dirty

    def _metadata_fields(self) -> tuple[MetadataField, ...]:
        return self._settings_store.current.metadata.fields

    # --- ochrona pracy ---------------------------------------------------------

    def maybe_discard_changes(self) -> bool:
        """Pyta o zgodę na utratę zmian; „Zapisz” zapisuje projekt.

        Zwraca True, gdy można kontynuować operację (brak zmian, zapisano albo
        użytkownik potwierdził odrzucenie), False, gdy anulował.
        """
        if not self.has_unsaved_work:
            return True
        if self.project_path is not None:
            title = tr("session.unsaved.title")
            text = tr("session.unsaved.text", name=self.project_name)
        else:
            title = tr("session.discard.title")
            text = tr("session.discard.text")
        answer = QMessageBox.question(
            self._parent,
            title,
            text,
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def sync_metadata(self) -> None:
        date = self._date_edit.date()
        self.document.set_metadata(
            self._author_edit.text(),
            "" if date == self._date_edit.minimumDate() else date.toString(DATE_FORMAT),
        )
        self.document.set_metadata_values(self._metadata_form.values())

    def new_document(self) -> None:
        if not self.maybe_discard_changes():
            return
        self._player.stop_and_unload()
        self._player_bar.reset()
        self._asr_panel.set_audio_available(False)
        self._asr_panel.restore_result(None)
        self._editor.blockSignals(True)
        self._editor.clear()
        self._editor.blockSignals(False)
        self._author_edit.clear()
        self._date_edit.setDate(QDate.currentDate())
        self._metadata_form.set_values({})
        self.document = Document()
        self.project_path = None
        self._set_audio(None)
        self.autosave.discard()
        self._on_reset()

    def import_audio(self, path: str) -> None:
        """Zmienia nagranie; tekst i metryczka zostają (REQ-09).

        Wynik ASR poprzedniego nagrania jest usuwany — jego segmenty nie
        mogą przewijać nowego pliku ani trafić do projektu (ACC-20).
        """
        if not self._confirm_audio_change(path):
            return
        try:
            self._player.load(path)
        except AppError as error:
            show_error(self._parent, tr("session.import_audio.error"), error)
            return
        self._player_bar.reset()
        self._asr_panel.set_audio_available(True)
        self._asr_panel.restore_result(None)
        self._set_audio(Path(path))
        if self.project_path is not None:
            self.document.touch()  # projekt wskazuje teraz inne nagranie
        if not self._metadata_form.value(SIGNATURE).strip():
            # Sama podpowiedź w pustej pracy nie jest pracą do ochrony —
            # zmiana nagrania lub zamknięcie nie pytają o nią (REQ-09).
            pristine = not self.has_unsaved_work and not self.document.text.strip()
            self._metadata_form.set_value(SIGNATURE, signature_from_audio(path))
            if pristine and self.project_path is None:
                self.document.mark_exported()
                self.document.mark_saved()

    def _confirm_audio_change(self, path: str) -> bool:
        """Pyta tylko, gdy coś zostanie zastąpione: nagranie albo wynik ASR."""
        has_asr = self._asr_panel.last_result is not None
        if self._player.source_path is None and not has_asr:
            return True
        text = tr("session.change_audio.text", name=Path(path).name)
        if has_asr:
            text = f"{text}\n\n{tr('session.change_audio.asr')}"
        answer = QMessageBox.question(
            self._parent,
            tr("session.change_audio.title"),
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def can_close(self) -> bool:
        """ACC-10: zamknięcie po potwierdzeniu i bez działającej transkrypcji."""
        if self._asr_panel.is_transcribing():
            # Działający QThread nie może zostać zniszczony razem z oknem.
            QMessageBox.information(
                self._parent,
                tr("session.transcribing.title"),
                tr("session.transcribing.text"),
            )
            return False
        if not self.maybe_discard_changes():
            return False
        if not self._stop_download():
            return False
        self._player.stop_and_unload()
        self.autosave.shutdown()
        self._stop_hashing()
        self._asr_panel.shutdown()
        return True

    def _stop_download(self) -> bool:
        """BUG-01: pobieranie modelu przerwane za zgodą, zanim okno zniknie."""
        if not self._asr_panel.is_downloading():
            return True
        answer = QMessageBox.question(
            self._parent,
            tr("session.downloading.title"),
            tr("session.downloading.text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        if self._asr_panel.cancel_download_and_wait(DOWNLOAD_SHUTDOWN_WAIT_MS):
            return True
        # Działający QThread nie może zostać zniszczony razem z oknem.
        QMessageBox.information(
            self._parent,
            tr("session.downloading.title"),
            tr("session.downloading.busy"),
        )
        return False

    # --- suma nagrania ---------------------------------------------------------

    def _set_audio(self, path: Path | None, sha256: str | None = None) -> None:
        """Bieżące nagranie; nieznana suma jest liczona w tle (PERF-03)."""
        self._cancel_hashing()
        if path is None:
            self._audio = None
            return
        absolute = path.resolve()
        self._audio = AudioRef(absolute_path=str(absolute), sha256=sha256 or "")
        if sha256 is None:
            self._hash_thread = self._start_hash(absolute)

    def _start_hash(self, path: Path) -> HashThread:
        # Bez rodzica Qt: wątek żyje, dopóki trzyma go ``_hash_threads`` albo
        # czekający ``wait_for`` (deleteLater usuwałby go w trakcie czekania).
        thread = HashThread(path, self.hash_impl)
        self._hash_threads.add(thread)
        # Metoda QObject (nie lambda): slot wykona się w wątku UI.
        thread.finished.connect(self._on_hash_thread_finished)
        thread.start()
        return thread

    def _on_hash_thread_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, HashThread):
            return
        thread.wait()  # ``finished`` pada tuż przed końcem wątku
        self._hash_threads.discard(thread)
        if self._hash_thread is thread:
            self._apply_hash(thread)
            self._hash_thread = None

    def _apply_hash(self, thread: HashThread) -> None:
        """Wpisuje sumę, gdy wątek dotyczy bieżącego nagrania."""
        audio = self._audio
        if (
            thread.digest
            and audio is not None
            and not audio.sha256
            and audio.absolute_path == str(thread.path)
        ):
            self._audio = replace(audio, sha256=thread.digest)

    def _cancel_hashing(self) -> None:
        """Porzuca liczenie dla poprzedniego nagrania (wynik zostanie pominięty)."""
        thread = self._hash_thread
        self._hash_thread = None
        if thread is not None:
            thread.requestInterruption()

    def _stop_hashing(self) -> None:
        """Przerywa wszystkie wątki sumy i czeka na nie (zamknięcie okna)."""
        self._cancel_hashing()
        for thread in list(self._hash_threads):
            thread.requestInterruption()
            thread.wait()

    def _wait_for_audio_hash(self) -> None:
        """Zapis projektu czeka na sumę nagrania liczoną w tle."""
        thread = self._hash_thread
        if thread is None:
            return
        wait_for(thread, self._parent, tr("session.audio_hash.progress"))
        self._apply_hash(thread)

    def _hash_now(self, path: Path) -> str | None:
        """Suma pliku od razu potrzebna (okno odświeża się w trakcie)."""
        thread = self._start_hash(path)
        wait_for(thread, self._parent, tr("session.audio_hash.progress"))
        return thread.digest

    # --- zapis projektu --------------------------------------------------------

    def save_project(self) -> bool:
        """Zapisuje projekt (bez pliku — pyta o nazwę); False = nie zapisano."""
        if self.project_path is None:
            return self.save_project_as()
        return self._write_project(self.project_path)

    def save_project_as(self) -> bool:
        path = ask_save_path(
            self._parent,
            tr("session.save.dialog"),
            self._default_project_name(),
            file_dialog_filter(),
            PROJECT_SUFFIX,
        )
        if path is None:
            return False
        return self._write_project(path)

    def _default_project_name(self) -> str:
        if self.project_path is not None:
            return str(self.project_path)
        signature = self.document.metadata.get(SIGNATURE, "").strip()
        if signature:
            return f"{signature}{PROJECT_SUFFIX}"
        source = self._player.source_path
        if source is not None:
            return str(source.with_suffix(PROJECT_SUFFIX))
        return f"{tr('session.default_project_name')}{PROJECT_SUFFIX}"

    def _write_project(self, path: Path) -> bool:
        self._wait_for_audio_hash()
        try:
            save_project(self.capture_state(), path)
        except AppError as error:
            show_error(self._parent, tr("session.save.error"), error)
            return False
        self.document.mark_saved()
        self.project_path = path
        self._settings_store.add_recent_project(str(path))
        self.autosave.discard()
        self._on_state_changed()
        return True

    def capture_state(self) -> ProjectState:
        """Bieżący stan pracy w formacie projektu."""
        document = self.document
        result = self._asr_panel.last_result
        has_audio = self._player.source_path is not None
        return ProjectState(
            text=document.text,
            superscript_ranges=tuple(document.superscript_ranges),
            author=document.author,
            date=document.date,
            metadata=dict(document.metadata),
            exported=not document.is_dirty,
            audio=self._audio if has_audio else None,
            player=self._player_bar.state(),
            asr=(
                None
                if result is None
                else AsrDraft(
                    text=result.text,
                    language=result.language,
                    segments=tuple(
                        AsrSegment(s.start_s, s.end_s, s.text, s.confidence)
                        for s in result.segments
                    ),
                )
            ),
            review=tuple(self._review.entries()),
        )

    # --- otwieranie projektu ---------------------------------------------------

    def open_project_dialog(self) -> None:
        if not self.maybe_discard_changes():
            return
        start = str(self.project_path.parent) if self.project_path else ""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self._parent, tr("session.open.dialog"), start, file_dialog_filter()
        )
        if path:
            self.open_project(path, confirm=False)

    def open_project(self, path: str | Path, confirm: bool = True) -> bool:
        """ACC-28/29: otwiera projekt; brak lub zmiana nagrania nie blokuje tekstu."""
        if confirm and not self.maybe_discard_changes():
            return False
        project_path = Path(path)
        try:
            state = load_project(project_path)
        except AppError as error:
            show_error(self._parent, tr("session.open.error"), error)
            if not project_path.exists():
                self._settings_store.remove_recent_project(str(project_path))
            return False
        audio, sha256 = self._locate_audio(state, project_path)
        self.apply_state(state, project_path, audio, saved=True, audio_sha256=sha256)
        self._settings_store.add_recent_project(str(project_path))
        return True

    def _locate_audio(
        self, state: ProjectState, project_path: Path | None
    ) -> tuple[Path | None, str | None]:
        """Nagranie projektu: ścieżka względna, bezwzględna albo wskazane ręcznie.

        Przy innej sumie SHA-256 użytkownik decyduje, czy użyć nagrania.
        Pusta suma w projekcie (np. autozapis przed jej policzeniem) oznacza
        brak weryfikacji. Zwraca nagranie i jego policzoną sumę (albo None).
        """
        ref = state.audio
        if ref is None:
            return None, None
        found = resolve_audio(ref, project_path)
        if found is None:
            answer = QMessageBox.question(
                self._parent,
                tr("session.audio_missing.title"),
                tr(
                    "session.audio_missing.text",
                    name=ref.name,
                    path=ref.absolute_path,
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None, None
            start = str(project_path.parent) if project_path else ""
            chosen, _selected_filter = QFileDialog.getOpenFileName(
                self._parent,
                tr("session.audio_locate.dialog", name=ref.name),
                start,
                audio_filter(),
            )
            if not chosen:
                return None, None
            found = Path(chosen)
        if not ref.sha256:
            return found, None
        digest = self._hash_now(found)
        if digest == ref.sha256:
            return found, digest
        answer = QMessageBox.question(
            self._parent,
            tr("session.audio_changed.title"),
            tr("session.audio_changed.text", name=found.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None, None
        return found, digest

    def apply_state(
        self,
        state: ProjectState,
        project_path: Path | None,
        audio_path: Path | None,
        saved: bool,
        audio_sha256: str | None = None,
    ) -> None:
        """Zastępuje bieżącą pracę stanem projektu (bez pytania o zmiany).

        ``audio_sha256`` to znana już suma nagrania; bez niej jest liczona w tle.
        """
        self._player.stop_and_unload()
        self._player_bar.reset()
        self._asr_panel.set_audio_available(False)
        self._review.finish()
        self._editor.load_content(state.text, state.superscript_ranges)
        self._author_edit.setText(state.author)
        date = QDate.fromString(state.date, DATE_FORMAT)
        self._date_edit.setDate(
            date if date.isValid() else self._date_edit.minimumDate()
        )
        self._metadata_form.set_values(state.metadata)

        self._set_audio(None)
        if audio_path is not None:
            try:
                self._player.load(audio_path)
            except AppError as error:
                show_error(self._parent, tr("session.project_audio.error"), error)
            else:
                self._player_bar.reset()
                self._asr_panel.set_audio_available(True)
                self._player_bar.restore_state(state.player)
                self._set_audio(audio_path, audio_sha256)
        self._asr_panel.restore_result(_transcription_result(state.asr))
        self._review.restore(state.review)

        document = Document(
            text=state.text,
            superscript_ranges=list(state.superscript_ranges),
            author=state.author,
            date=state.date if date.isValid() else "",
            metadata=normalized(state.metadata),
            revision=1,
        )
        if saved:
            document.mark_saved()
        if state.exported and saved:
            document.mark_exported()
        self.document = document
        self.project_path = project_path
        self._on_state_changed()

    # --- import DOCX i odzyskiwanie --------------------------------------------

    def import_docx_dialog(self) -> None:
        if not self.maybe_discard_changes():
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self._parent, tr("session.import_docx.dialog"), "", tr("export.filter")
        )
        if path:
            self.import_docx(path, confirm=False)

    def import_docx(self, path: str | Path, confirm: bool = True) -> bool:
        """ACC-33: nowy, niezapisany projekt bez nagrania z treścią DOCX."""
        if confirm and not self.maybe_discard_changes():
            return False
        try:
            imported = import_docx(path, self._metadata_fields())
        except AppError as error:
            show_error(self._parent, tr("session.import_docx.title"), error)
            return False
        state = ProjectState(
            text=imported.text,
            superscript_ranges=tuple(imported.superscript_ranges),
            author=imported.author,
            date=imported.date,
            metadata=imported.metadata,
        )
        self.apply_state(state, None, None, saved=False)
        QMessageBox.information(
            self._parent,
            tr("session.import_docx.title"),
            import_summary(Path(path).name, imported.report.lines()),
        )
        return True

    def offer_recovery(self) -> bool:
        """ACC-30: przy starcie proponuje odzyskanie osieroconych autozapisów."""
        candidates = find_orphans(self.autosave.directory, self.autosave.session_id)
        if not candidates:
            return False
        dialog = RecoveryDialog(candidates, self._parent)
        dialog.exec()
        chosen = dialog.chosen
        for candidate in dialog.candidates:
            if candidate is not chosen:
                candidate.release()
        if chosen is None or chosen.state is None:
            return False
        state = chosen.state
        audio, sha256 = self._locate_audio(state, None)
        self.apply_state(state, None, audio, saved=False, audio_sha256=sha256)
        # Odzyskana praca ma swój autozapis w bieżącej sesji.
        chosen.remove()
        self.autosave.save_now()
        return True


def import_summary(name: str, skipped: list[str]) -> str:
    """Treść raportu po imporcie DOCX (pozycje z ``ImportReport.lines``)."""
    summary = (
        tr("session.import_docx.skipped", items="\n• ".join(skipped))
        if skipped
        else tr("session.import_docx.lossless")
    )
    return f"{tr('session.import_docx.summary', name=name)}\n\n{summary}"


def _transcription_result(draft: AsrDraft | None) -> TranscriptionResult | None:
    if draft is None:
        return None
    return TranscriptionResult(
        text=draft.text,
        language=draft.language,
        segments=tuple(
            SegmentResult(s.start_s, s.end_s, s.text, s.confidence)
            for s in draft.segments
        ),
    )
