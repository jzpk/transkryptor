"""Główne okno ręcznej transkrypcji.

Składa pasek narzędzi (``ui/toolbar.py``), kartę odtwarzacza, kartę edytora
z polami metadanych, metryczką i paskiem wyszukiwania, panel ostrzeżeń,
panel ASR oraz pasek stanu. Logikę deleguje do kontrolerów: przegląd szkicu
ASR (``ui/review.py``), stan sesji, projekt i autozapis (``ui/session.py``,
``ui/autosave.py``), eksport
(``ui/export_controller.py``), odtwarzacz (``ui/player_controller.py``)
i wyszukiwanie (``ui/search_controller.py``). Okno uruchamia nieblokującą
walidację ``notation.validate`` z debounce — reguły pozostają w module
``notation``, UI je prezentuje — i stosuje ustawienia bez restartu.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.asr.manager import ModelManager
from transkryptor.audio.player import AudioPlayer
from transkryptor.document.model import Document
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.settings import Settings
from transkryptor.ui import icons
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.export_controller import ExportController
from transkryptor.ui.layout import (
    author_field,
    buddy_caption,
    card,
    date_field,
    header_row,
    label,
    shrinkable,
    side_dock,
    words_label,
)
from transkryptor.ui.loading_overlay import LoadingOverlay
from transkryptor.ui.markers import marker_text
from transkryptor.ui.messages import show_error
from transkryptor.ui.metadata_form import MetadataForm
from transkryptor.ui.notation_controller import NotationController
from transkryptor.ui.player_bar import PlayerBar
from transkryptor.ui.player_controller import PlayerController
from transkryptor.ui.review import (
    DRAFT_APPEND,
    DRAFT_REPLACE,
    ReviewController,
    ask_draft_placement,
    draft_placement_box,
)
from transkryptor.ui.search_bar import SearchBar
from transkryptor.ui.search_controller import SearchController
from transkryptor.ui.session import SessionController
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.settings_store import SettingsStore
from transkryptor.ui.shortcuts import tooltip_with_shortcut as _tooltip
from transkryptor.ui.theme import apply_theme, resolve_tokens, set_props, tokens
from transkryptor.ui.toolbar import MainToolbar, ToolbarHandlers
from transkryptor.ui.update_controller import UpdateController
from transkryptor.ui.warnings_panel import WarningsPanel

# Stałe przeniesione do kontrolerów, re-eksportowane dla zgodności importów.
__all__ = [
    "DRAFT_APPEND",
    "DRAFT_REPLACE",
    "MainWindow",
]

STATUS_MESSAGE_MS = 5000
# Pełna synchronizacja edytora z dokumentem (licznik słów, stan) po przerwie
# w pisaniu; zapis, eksport i walidacja synchronizują od razu.
SYNC_DEBOUNCE_MS = 300
WINDOW_TITLE = "Transkryptor"


class MainWindow(QMainWindow):
    """Widok główny ręcznej transkrypcji."""

    def __init__(
        self, parent=None, settings_store: SettingsStore | None = None
    ) -> None:
        super().__init__(parent)
        self.player = AudioPlayer(self)
        if settings_store is None:
            settings_store = SettingsStore(parent=self)
            settings_store.load()
        self.settings_store = settings_store
        self._ui_locked = False

        self.author_edit = author_field()
        self.date_edit = date_field()
        self.metadata_form = MetadataForm(settings_store.current.metadata.fields)

        self.editor = TranscriptionEditor()
        self.search_bar = SearchBar()
        self.player_bar = PlayerBar(self.player, settings_store.current.player)
        self.warnings_panel = WarningsPanel()
        self.warnings_panel.set_warnings([])
        self.warning_count_label = label("", "badge")

        self.model_manager = ModelManager()
        self.asr_panel = AsrPanel(
            self.model_manager,
            audio_path_provider=lambda: self.player.source_path,
        )

        self.review = ReviewController(
            self.editor,
            self.asr_panel,
            self,
            # Późne wiązanie: testy podmieniają ``_ask_draft_placement``.
            ask_placement=lambda: self._ask_draft_placement(),
            ellipsis_style=lambda: self._ellipsis_style,
        )
        self.session = SessionController(
            self,
            self.editor,
            self.player,
            self.player_bar,
            self.asr_panel,
            self.review,
            self.author_edit,
            self.date_edit,
            self.metadata_form,
            settings_store,
            on_reset=self._on_session_reset,
            on_state_changed=self._on_session_state_changed,
        )
        self.exporter = ExportController(
            self,
            lambda: self.document,
            self.date_edit,
            lambda: self.settings_store.current.metadata.fields,
            self._update_title,
        )
        self.search = SearchController(self.editor, self.search_bar, self)
        self.notation = NotationController(
            self.editor,
            self.warnings_panel,
            self.warning_count_label,
            lambda: self.document,
            lambda: self._ellipsis_style,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
        )
        self._validation_timer = self.notation.timer
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(SYNC_DEBOUNCE_MS)
        self._sync_timer.timeout.connect(self._update_title)

        self._build_layout()
        # Bez połączeń sieciowych przy tworzeniu okna: sprawdzanie startuje
        # punkt wejścia (``__main__.main``) przez ``updates.start_automatic``.
        self.updates = UpdateController(self)
        self._build_toolbar()
        self.player_controller = PlayerController(self, self.player, self.player_bar)
        self.player_actions = self.player_controller.actions
        self.search_actions = self.search.create_actions(self)
        self._build_status_bar()
        self.loading_overlay = LoadingOverlay(self)
        self._connect_signals()
        self._apply_settings(settings_store.current)
        self._update_title()
        self.notation.update_warning_count()

    @property
    def document(self) -> Document:
        return self.session.document

    @property
    def _ellipsis_style(self) -> EllipsisStyle:
        return self.settings_store.current.notation.ellipsis

    # --- składanie UI -----------------------------------------------------

    def _build_layout(self) -> None:
        # Nagłówek karty edytora: tytuł oraz metadane trafiające do DOCX.
        self.word_count_label = label("", "badge")
        header = header_row(
            (16, 10, 12, 10),
            label(tr("main.transcription"), "section"),
            self.word_count_label,
            None,
            buddy_caption(tr("main.author"), self.author_edit),
            self.author_edit,
            8,
            buddy_caption(tr("main.date"), self.date_edit),
            self.date_edit,
        )
        editor_card = card(
            header, self.metadata_form, self.editor, self.search_bar, stretch_index=1
        )

        self.unify_ellipses_action = self.notation.create_unify_action(self)
        unify_button = QToolButton()
        unify_button.setDefaultAction(self.unify_ellipses_action)
        warnings_header = header_row(
            (16, 8, 16, 8),
            label(tr("main.warnings"), "section"),
            self.warning_count_label,
            None,
            shrinkable(label(tr("main.warnings.hint"), "muted")),
            unify_button,
        )
        warnings_card = card(warnings_header, self.warnings_panel)
        warnings_card.setMinimumHeight(96)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(editor_card)
        splitter.addWidget(warnings_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([520, 140])

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(self.player_bar)
        layout.addWidget(splitter, stretch=1)

        container = QWidget()
        container.setObjectName("central")
        container.setLayout(layout)
        self.setCentralWidget(container)
        self._central = container
        self.resize(1280, 800)

        self.asr_dock = side_dock(self, tr("main.asr_dock"), "asr_dock", self.asr_panel)

    def _build_toolbar(self) -> None:
        bar = MainToolbar(
            self,
            self.asr_dock.toggleViewAction(),
            self.updates.check_action,
            ToolbarHandlers(
                superscript=self._on_superscript,
                marker=self.notation.insert_marker,
                settings=self._on_settings,
                new_document=self._on_new_document,
                export=self._on_export,
                close=self.close,
                open_project=self.session.open_project_dialog,
                open_recent=lambda path: self.session.open_project(path),
                clear_recent=self.settings_store.clear_recent_projects,
                recent_projects=self.settings_store.recent_projects,
                save_project=self.session.save_project,
                save_project_as=self.session.save_project_as,
                import_docx=self.session.import_docx_dialog,
                export_anonymized=lambda: self.exporter.export(anonymize=True),
            ),
        )
        self.toolbar = bar.toolbar
        self.superscript_action = bar.superscript_action
        self.marker_actions = bar.marker_actions
        self.asr_panel_action = bar.asr_panel_action
        self.settings_action = bar.settings_action
        self.new_action = bar.new_action
        self.export_action = bar.export_action
        self.export_anonymized_action = bar.export_anonymized_action
        self.close_action = bar.close_action
        self.open_action = bar.open_action
        self.save_action = bar.save_action
        self.save_as_action = bar.save_as_action
        self.import_docx_action = bar.import_docx_action
        self.main_toolbar = bar

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self.export_status_label = QLabel()
        status.addPermanentWidget(self.export_status_label)

    def _connect_signals(self) -> None:
        self.editor.document().contentsChanged.connect(self._on_editor_changed)
        self.author_edit.textChanged.connect(self._on_metadata_changed)
        self.date_edit.dateChanged.connect(self._on_metadata_changed)
        self.metadata_form.changed.connect(self._on_metadata_changed)
        self.player_bar.import_requested.connect(self._on_import_audio)
        self.settings_store.settings_changed.connect(self._apply_settings)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            # Motyw „zgodny z systemem” podąża za przełączeniem trybu systemu.
            app.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)
        self.asr_panel.seek_requested.connect(self.player_controller.seek_to_segment)
        self.player.playback_error.connect(
            lambda error: self._show_error(tr("main.playback_error"), error)
        )
        self.asr_panel.draft_ready.connect(self._on_draft_ready)
        self.asr_panel.review_item_activated.connect(self.review.activate)
        self.asr_panel.review_item_apply_requested.connect(self._on_apply_review_item)
        self.asr_panel.review_finish_requested.connect(self.review.finish)
        self.asr_panel.transcription_started.connect(self._on_transcription_started)
        self.asr_panel.transcription_finished.connect(self._on_transcription_finished)
        self.asr_panel.transcription_progress.connect(self.loading_overlay.set_progress)
        self.loading_overlay.cancel_requested.connect(
            self.asr_panel.cancel_transcription
        )

    # --- ustawienia i notacja ---------------------------------------------

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self.settings_store.current, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.settings_store.save(dialog.settings())

    def _apply_settings(self, settings: Settings) -> None:
        """Stosuje ustawienia do komponentów bez restartu (ACC-17)."""
        self._apply_theme(settings.appearance.theme)
        self.player_bar.apply_settings(settings.player)
        self.editor.apply_settings(settings.editor)
        self.metadata_form.set_fields(settings.metadata.fields)
        self.session.autosave.configure(settings.project)
        self.asr_panel.set_segment_preroll_ms(settings.player.segment_preroll_ms)
        # ACC-25: tekst się nie zmienia — tylko kolejne wstawienia i walidacja.
        pause = self.marker_actions["pause"]
        pause_marker = marker_text("pause", settings.notation.ellipsis).strip()
        pause.setToolTip(
            _tooltip(
                tr("toolbar.insert", marker=pause_marker), pause.shortcut().toString()
            )
        )
        self.notation.schedule_validation()

    def _on_color_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        self._apply_theme(self.settings_store.current.appearance.theme)

    def _apply_theme(self, choice: str) -> None:
        """Przełącza motyw aplikacji i przerysowuje ikony w nowych kolorach."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        target = resolve_tokens(choice, app)
        if target is tokens():
            return
        apply_theme(app, target)
        icons.refresh(self)
        # Ikony listy ostrzeżeń powstają przy walidacji.
        self.notation.schedule_validation()

    def _on_superscript(self) -> None:
        # ``mergeCharFormat`` emituje ``contentsChanged`` — synchronizacja
        # idzie przez ``_on_editor_changed``.
        self.editor.toggle_superscript()

    def _on_editor_changed(self) -> None:
        """Każde naciśnięcie klawisza: tylko znacznik zmiany i debounce (PERF-02)."""
        self.session.mark_editor_changed()
        self._show_dirty_state(unsaved=True, dirty=True)
        self._sync_timer.start()
        self.notation.schedule_validation()

    def _on_metadata_changed(self) -> None:
        self.session.sync_metadata()
        self._update_title()

    # --- delegaty kontrolerów ---------------------------------------------

    def _on_new_document(self) -> None:
        self.session.new_document()

    def _on_session_reset(self) -> None:
        self.notation.clear()
        self.review.finish()
        self._update_title()

    def _on_session_state_changed(self) -> None:
        """Projekt otwarty, zapisany, odzyskany albo zaimportowany."""
        self._update_title()
        self.notation.schedule_validation()

    def _on_import_audio(self, path: str) -> None:
        self.session.import_audio(path)

    def _on_draft_ready(self, text: str) -> None:
        self.review.insert_draft(text)

    def _ask_draft_placement(self) -> str | None:
        return ask_draft_placement(self)

    def draft_placement_box(self) -> tuple[QMessageBox, object, object]:
        """Dialog wyboru miejsca szkicu: (okno, „Zastąp całość”, „Dopisz”)."""
        return draft_placement_box(self)

    def _on_apply_review_item(self, index: int) -> None:
        self.review.apply(index)

    def _on_export(self) -> None:
        self.exporter.export()

    def maybe_discard_changes(self) -> bool:
        return self.session.maybe_discard_changes()

    def closeEvent(self, event: QCloseEvent) -> None:
        """ACC-10: ostrzeżenie przed utratą pracy przy zamknięciu."""
        if self.session.can_close():
            event.accept()
        else:
            event.ignore()

    def _show_error(self, title: str, error: AppError) -> None:
        show_error(self, title, error)

    # --- blokada podczas ASR ----------------------------------------------

    def _on_transcription_started(self) -> None:
        """Blokuje okno na czas transkrypcji; aktywne zostaje tylko anulowanie.

        Nakładka przechwytuje mysz, a wyłączone widżety i akcje odcinają
        klawiaturę i skróty (także te o zasięgu całej aplikacji).
        """
        self._set_ui_locked(True)
        self.session.autosave.pause()
        self.loading_overlay.start()

    def _on_transcription_finished(self) -> None:
        self.loading_overlay.stop()
        self._set_ui_locked(False)
        self.session.autosave.resume()

    def _set_ui_locked(self, locked: bool) -> None:
        self._ui_locked = locked
        self._central.setEnabled(not locked)
        self.asr_panel.setEnabled(not locked)
        for toolbar in self.findChildren(QToolBar):
            toolbar.setEnabled(not locked)
        for action in (
            self.superscript_action,
            *self.marker_actions.values(),
            self.new_action,
            self.open_action,
            self.save_action,
            self.save_as_action,
            self.import_docx_action,
            self.export_action,
            self.export_anonymized_action,
            self.settings_action,
            self.unify_ellipses_action,
            *self.search_actions.values(),
        ):
            action.setEnabled(not locked)
        self.player_controller.set_locked(locked)

    # --- stan --------------------------------------------------------------

    def _update_title(self) -> None:
        """Odświeża tytuł okna, licznik słów i stan eksportu w pasku stanu.

        Gwiazdka w tytule: niezapisane zmiany projektu, a bez pliku
        projektu — niewyeksportowane zmiany.
        """
        self._sync_timer.stop()
        document = self.document
        words = len(document.text.split())
        self.word_count_label.setText(f"{words} {words_label(words)}")
        self._show_dirty_state(self.session.has_unsaved_work, document.is_dirty)

    def _show_dirty_state(self, unsaved: bool, dirty: bool) -> None:
        """Gwiazdka w tytule i stan eksportu w pasku stanu."""
        marker = "*" if unsaved else ""
        name = self.session.project_name
        self.setWindowTitle(
            f"{WINDOW_TITLE} — {name}{marker}" if name else f"{WINDOW_TITLE}{marker}"
        )
        self.export_status_label.setText(
            tr("session.status_dirty") if dirty else tr("session.status_clean")
        )
        set_props(
            self.export_status_label, role="badge", tone="warning" if dirty else ""
        )

    def run_validation_now(self) -> None:
        """Pomocnicze dla testów: natychmiastowa walidacja bez debounce."""
        self.notation.run_validation()
