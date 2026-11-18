"""Stan sesji: dokument, projekt, nagranie i ochrona pracy.

``SessionController`` jest właścicielem modelu ``Document`` bieżącej sesji
i pliku projektu (``.transkr``). Pilnuje, by praca nie zginęła bez
potwierdzenia (REQ-09, ACC-10, ACC-31) - przy nowym dokumencie, otwarciu
projektu, imporcie DOCX i zamknięciu: dokument z plikiem projektu pyta
o niezapisane zmiany, dokument bez pliku - o niewyeksportowane. Okno pytania
ma opcję „Zapisz”. Zmiana nagrania nie porzuca tekstu, więc ma osobne
pytanie: tylko gdy zastępuje inne nagranie albo usuwa wynik ASR.

Sumę SHA-256 nagrania liczy wątek w tle (``ui/audio_hash.py``); zapis
projektu czeka na nią, autozapis - nie (pusta suma = brak weryfikacji).

Kontroler zapisuje i otwiera projekty (ACC-28, ACC-29), importuje DOCX
(ACC-33) i odzyskuje pracę z autozapisu (ACC-30, ``ui/autosave.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from transkryptor import diagnostics
from transkryptor.document.metadata import (
    SIGNATURE,
    MetadataField,
    asr_context_hint,
    normalized,
    signature_from_audio,
)
from transkryptor.document.model import Document
from transkryptor.document.project import (
    PROJECT_SUFFIX,
    ProjectState,
    file_dialog_filter,
    load_project,
    save_project,
)
from transkryptor.errors import AppError
from transkryptor.export.docx_import import import_docx
from transkryptor.i18n import tr
from transkryptor.ui.audio_hash import AudioHashing
from transkryptor.ui.audio_locator import AudioLocator
from transkryptor.ui.autosave import AutosaveController
from transkryptor.ui.messages import show_error
from transkryptor.ui.project_state import ProjectAnnotations, ProjectStateMapper
from transkryptor.ui.recovery import RecoveryController
from transkryptor.ui.save_location import SaveLocation
from transkryptor.ui.session_prompts import (
    Discard,
    ask_discard,
    confirm_audio_change,
    confirm_stop_download,
    tell_download_busy,
    tell_transcribing,
)
from transkryptor.ui.session_views import SessionViews
from transkryptor.ui.settings_store import SettingsStore

logger = logging.getLogger(__name__)

# Ile zamknięcie okna czeka na przerwanie pobierania modelu.
DOWNLOAD_SHUTDOWN_WAIT_MS = 5000


class SessionEvents(QObject):
    """Zdarzenia sesji dla okna (zamiast przekazywanych callbacków)."""

    # Nowy, pusty dokument.
    reset = Signal()
    # Projekt otwarty, zapisany, odzyskany albo zaimportowany.
    state_changed = Signal()
    # Projekt zapisany do pliku (przed ``state_changed``).
    saved = Signal()
    # Import DOCX zaraz zastąpi bieżącą pracę (np. migawka automatyczna).
    about_to_import = Signal()
    # Wczytywany projekt ma zapamiętany profil notacji (nazwa; przed tekstem).
    profile_requested = Signal(str)


class SessionController(QObject):
    """Dokument sesji, plik projektu i operacje, które mogą porzucić pracę."""

    def __init__(
        self,
        dialog_parent: QWidget,
        views: SessionViews,
        annotations: ProjectAnnotations,
        settings_store: SettingsStore,
    ) -> None:
        super().__init__(dialog_parent)
        self._document = Document()
        # Edytor zmienił się od ostatniej synchronizacji z ``_document``.
        self._editor_pending = False
        self.project_path: Path | None = None
        # Bieżące nagranie i jego suma SHA-256 liczona w tle.
        self.hashing = AudioHashing(dialog_parent, self)
        self._parent = dialog_parent
        self._editor = views.editor
        self._player = views.player
        self._player_bar = views.player_bar
        self._asr_panel = views.asr
        self._review = annotations.review
        self._sync = annotations.sync
        self._verification = annotations.verification
        self._metadata = views.metadata
        self._settings_store = settings_store
        self._state = ProjectStateMapper(
            views, annotations, lambda: settings_store.current.profiles.active
        )
        self._locator = AudioLocator(dialog_parent, self.hashing.hash_now)
        # Wspólny folder okien zapisu i otwierania (projekt, eksport, paczka).
        self.save_location = SaveLocation(settings_store, lambda: self.project_path)
        self.events = SessionEvents(self)
        # Wołane przed zastąpieniem treści edytora (nowy dokument, projekt,
        # import DOCX, odzyskanie) - np. koniec porównania wersji.
        self.before_replace: Callable[[], None] = lambda: None
        self.autosave = AutosaveController(
            self.capture_state, lambda: self.document, self
        )
        self._recovery = RecoveryController(
            dialog_parent,
            self.autosave,
            self._locator.locate,
            lambda state, audio, sha256: self.apply_state(
                state, None, audio, saved=False, audio_sha256=sha256
            ),
        )

    @property
    def document(self) -> Document:
        """Dokument sesji zsynchronizowany z edytorem.

        Edycja tylko zaznacza zmianę (:meth:`mark_editor_changed`); pełna
        synchronizacja odbywa się tu, przy pierwszym odczycie - zapis,
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
    def audio_sha256(self) -> str | None:
        """Suma SHA-256 bieżącego nagrania (None - brak albo jeszcze liczona)."""
        audio = self.hashing.audio
        return audio.sha256 if audio is not None else None

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
        name = self.project_name if self.project_path is not None else None
        answer = ask_discard(self._parent, name)
        if answer is Discard.SAVE:
            return self.save_project()
        return answer is Discard.DISCARD

    def sync_metadata(self) -> None:
        self.document.set_metadata(
            self._metadata.author_text(), self._metadata.date_text()
        )
        values = self._metadata.form.values()
        self.document.set_metadata_values(values)
        self._asr_panel.set_context_default(asr_context_hint(values))

    def asr_context_changed(self) -> None:
        """Kontekst lub słownik ASR to dane projektu - nie tekst eksportu."""
        self.project_data_changed()

    def project_data_changed(self) -> None:
        """Zmiana danych projektu spoza tekstu eksportu (kontekst ASR, kotwice).

        Zmiana oznacza projekt jako niezapisany, ale nie wywołuje ostrzeżenia
        o niewyeksportowanej pracy, jeśli tekst był wyeksportowany.
        """
        exported = not self.document.is_dirty
        self.document.touch()
        if exported:
            self.document.mark_exported()
        self.events.state_changed.emit()

    def comments_changed(self) -> None:
        """Komentarze trafiają do eksportu DOCX - zmiana jak zmiana tekstu."""
        self.document.touch()
        self.events.state_changed.emit()

    def new_document(self) -> None:
        if not self.maybe_discard_changes():
            return
        self.before_replace()
        self._player.stop_and_unload()
        self._player_bar.reset()
        self._asr_panel.set_audio_available(False)
        self._state.clear()
        self.document = Document()
        self.project_path = None
        self.hashing.set(None)
        self.autosave.discard()
        self.events.reset.emit()

    def import_audio(self, path: str) -> None:
        """Zmienia nagranie; tekst i metryczka zostają (REQ-09).

        Wynik ASR poprzedniego nagrania jest usuwany - jego segmenty nie
        mogą przewijać nowego pliku ani trafić do projektu (ACC-20).
        """
        if not self._confirm_audio_change(path):
            return
        logger.info("Loading recording: %s", diagnostics.file_summary(path))
        try:
            self._player.load(path)
        except AppError as error:
            show_error(self._parent, tr("session.import_audio.error"), error)
            return
        self._player_bar.reset()
        self._asr_panel.set_audio_available(True)
        self._asr_panel.restore_result(None)
        # Kotwice i sprawdzone zakresy wskazują czasy poprzedniego nagrania.
        self._sync.clear()
        self._verification.clear()
        self.hashing.set(Path(path))
        if self.project_path is not None:
            self.document.touch()  # projekt wskazuje teraz inne nagranie
        if not self._metadata.form.value(SIGNATURE).strip():
            # Sama podpowiedź w pustej pracy nie jest pracą do ochrony -
            # zmiana nagrania lub zamknięcie nie pytają o nią (REQ-09).
            pristine = not self.has_unsaved_work and not self.document.text.strip()
            self._metadata.form.set_value(SIGNATURE, signature_from_audio(path))
            if pristine and self.project_path is None:
                self.document.mark_exported()
                self.document.mark_saved()

    def _confirm_audio_change(self, path: str) -> bool:
        """Pyta tylko, gdy coś zostanie zastąpione: nagranie albo wynik ASR."""
        has_asr = self._asr_panel.last_result is not None
        has_anchors = self._sync.has_anchors()
        has_verified = bool(self._verification.ranges)
        if (
            self._player.source_path is None
            and not has_asr
            and not has_anchors
            and not has_verified
        ):
            return True
        return confirm_audio_change(
            self._parent,
            Path(path).name,
            has_asr=has_asr,
            has_anchors=has_anchors,
            has_verified=has_verified,
        )

    def can_close(self) -> bool:
        """ACC-10: zamknięcie po potwierdzeniu i bez działającej transkrypcji."""
        if self._asr_panel.is_transcribing():
            # Działający QThread nie może zostać zniszczony razem z oknem.
            tell_transcribing(self._parent)
            return False
        if not self.maybe_discard_changes():
            return False
        if not self._stop_download():
            return False
        self._player.stop_and_unload()
        self.autosave.shutdown()
        self.hashing.stop()
        self._asr_panel.shutdown()
        return True

    def _stop_download(self) -> bool:
        """BUG-01: pobieranie modelu przerwane za zgodą, zanim okno zniknie."""
        if not self._asr_panel.is_downloading():
            return True
        if not confirm_stop_download(self._parent):
            return False
        if self._asr_panel.cancel_download_and_wait(DOWNLOAD_SHUTDOWN_WAIT_MS):
            return True
        # Działający QThread nie może zostać zniszczony razem z oknem.
        tell_download_busy(self._parent)
        return False

    # --- suma nagrania ---------------------------------------------------------

    def wait_for_audio_hash(self) -> None:
        """Zapis projektu czeka na sumę nagrania liczoną w tle."""
        self.hashing.wait()

    # --- zapis projektu --------------------------------------------------------

    def save_project(self) -> bool:
        """Zapisuje projekt (bez pliku - pyta o nazwę); False = nie zapisano."""
        if self.project_path is None:
            return self.save_project_as()
        return self._write_project(self.project_path)

    def save_project_as(self) -> bool:
        path = self.save_location.ask(
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
        """Nazwa pliku projektu; folder wybiera ``SaveLocation``."""
        if self.project_path is not None:
            return self.project_path.name
        signature = self.document.metadata.get(SIGNATURE, "").strip()
        if signature:
            return f"{signature}{PROJECT_SUFFIX}"
        source = self._player.source_path
        if source is not None:
            return source.with_suffix(PROJECT_SUFFIX).name
        return f"{tr('session.default_project_name')}{PROJECT_SUFFIX}"

    def _write_project(self, path: Path) -> bool:
        self.wait_for_audio_hash()
        state = self.capture_state()
        logger.info("Saving project: %d characters of text", len(state.text))
        try:
            save_project(state, path)
        except AppError as error:
            show_error(self._parent, tr("session.save.error"), error)
            return False
        self.document.mark_saved()
        self.project_path = path
        self._settings_store.add_recent_project(str(path))
        self.autosave.discard()
        self.events.saved.emit()
        self.events.state_changed.emit()
        return True

    def capture_state(self) -> ProjectState:
        """Bieżący stan pracy w formacie projektu."""
        return self._state.capture(self.document, self.hashing.audio)

    # --- otwieranie projektu ---------------------------------------------------

    def open_project_dialog(self) -> None:
        if not self.maybe_discard_changes():
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self._parent,
            tr("session.open.dialog"),
            self.save_location.start_dir(),
            file_dialog_filter(),
        )
        if path:
            self.open_project(path, confirm=False)

    def open_project(
        self, path: str | Path, confirm: bool = True, use_profile: bool = True
    ) -> bool:
        """ACC-28/29: otwiera projekt; brak lub zmiana nagrania nie blokuje tekstu.

        ``use_profile=False`` - bez przełączania na profil notacji projektu
        (paczka: o ustawieniach zdecydował już odbiorca).
        """
        if confirm and not self.maybe_discard_changes():
            return False
        project_path = Path(path)
        logger.info("Opening project: %s", diagnostics.file_summary(project_path))
        try:
            state = load_project(project_path)
        except AppError as error:
            show_error(self._parent, tr("session.open.error"), error)
            if not project_path.exists():
                self._settings_store.remove_recent_project(str(project_path))
            return False
        audio, sha256 = self._locator.locate(state, project_path)
        if not use_profile:
            state = replace(state, profile="")
        self.apply_state(state, project_path, audio, saved=True, audio_sha256=sha256)
        self._settings_store.add_recent_project(str(project_path))
        return True

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
        self.before_replace()
        # Profil najpierw: pola metryczki i reguły walidatora pochodzą z niego.
        if state.profile:
            self.events.profile_requested.emit(state.profile)
        self._player.stop_and_unload()
        self._player_bar.reset()
        self._asr_panel.set_audio_available(False)
        self._review.finish()
        date_valid = self._state.restore_content(state)

        self.hashing.set(None)
        if audio_path is not None:
            try:
                self._player.load(audio_path)
            except AppError as error:
                show_error(self._parent, tr("session.project_audio.error"), error)
            else:
                self._player_bar.reset()
                self._asr_panel.set_audio_available(True)
                self._player_bar.restore_state(state.player)
                self.hashing.set(audio_path, audio_sha256)
        self._state.restore_annotations(state)

        document = Document(
            text=state.text,
            superscript_ranges=list(state.superscript_ranges),
            author=state.author,
            date=state.date if date_valid else "",
            metadata=normalized(state.metadata),
            speakers=list(state.speakers),
            paragraph_speakers=dict(state.paragraph_speakers),
            revision=1,
        )
        if saved:
            document.mark_saved()
        if state.exported and saved:
            document.mark_exported()
        self.document = document
        self.project_path = project_path
        self.events.state_changed.emit()

    # --- import DOCX i odzyskiwanie --------------------------------------------

    def import_docx_dialog(self) -> None:
        if not self.maybe_discard_changes():
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self._parent,
            tr("session.import_docx.dialog"),
            self.save_location.start_dir(),
            tr("export.filter"),
        )
        if path:
            self.import_docx(path, confirm=False)

    def import_docx(self, path: str | Path, confirm: bool = True) -> bool:
        """ACC-33: nowy, niezapisany projekt bez nagrania z treścią DOCX."""
        if confirm and not self.maybe_discard_changes():
            return False
        logger.info("Importing DOCX: %s", diagnostics.file_summary(path))
        try:
            imported = import_docx(path, self._metadata_fields())
        except AppError as error:
            show_error(self._parent, tr("session.import_docx.title"), error)
            return False
        self.events.about_to_import.emit()
        state = ProjectState(
            text=imported.text,
            superscript_ranges=tuple(imported.superscript_ranges),
            author=imported.author,
            date=imported.date,
            metadata=imported.metadata,
            speakers=imported.speakers,
            paragraph_speakers=imported.paragraph_speakers,
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
        return self._recovery.offer()


def import_summary(name: str, skipped: list[str]) -> str:
    """Treść raportu po imporcie DOCX (pozycje z ``ImportReport.lines``)."""
    summary = (
        tr("session.import_docx.skipped", items="\n• ".join(skipped))
        if skipped
        else tr("session.import_docx.lossless")
    )
    return f"{tr('session.import_docx.summary', name=name)}\n\n{summary}"
