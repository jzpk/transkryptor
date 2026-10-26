"""Główne okno ręcznej transkrypcji.

Składa pasek narzędzi (``ui/toolbar.py``), kartę odtwarzacza, kartę edytora
z polami metadanych, metryczką i paskiem wyszukiwania, panel ostrzeżeń,
panel ASR oraz pasek stanu. Logikę deleguje do kontrolerów: przegląd szkicu
ASR (``ui/review.py``), stan sesji, projekt i autozapis (``ui/session.py``,
``ui/autosave.py``), eksport
(``ui/export_controller.py``), odtwarzacz (``ui/player_controller.py``)
i wyszukiwanie (``ui/search_controller.py``). Okno uruchamia nieblokującą
walidację ``notation.validate`` z debounce - reguły pozostają w module
``notation``, UI je prezentuje - i stosuje ustawienia bez restartu.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
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

from transkryptor import __version__
from transkryptor.asr.engine import (
    TranscriptionResult,
    draft_line_speakers,
    draft_text,
)
from transkryptor.asr.manager import ModelManager
from transkryptor.asr.models import model_by_key
from transkryptor.audio.player import AudioPlayer
from transkryptor.document.model import Document
from transkryptor.document.readiness import ReadinessReport, build_report
from transkryptor.document.speakers import (
    Speaker,
    informant_spans,
    speakers_for_clusters,
)
from transkryptor.errors import AppError
from transkryptor.feedback import report_form_url
from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.notation.rules import PhoneticRule
from transkryptor.notation.suggestions import rule_infos
from transkryptor.settings import ExportSettings, Settings
from transkryptor.ui import icons
from transkryptor.ui.asr_panel import AsrPanel
from transkryptor.ui.audio_filters import AudioFilterController
from transkryptor.ui.changelog_dialog import ChangelogDialog
from transkryptor.ui.comments_controller import CommentsController
from transkryptor.ui.compare_controller import CompareController
from transkryptor.ui.corpus_controller import CorpusController
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.export_controller import ExportController
from transkryptor.ui.fonts import text_font_family
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
from transkryptor.ui.learning_controller import RuleLearningController
from transkryptor.ui.loading_overlay import LoadingOverlay
from transkryptor.ui.markers import marker_text
from transkryptor.ui.messages import show_error
from transkryptor.ui.metadata_form import MetadataForm
from transkryptor.ui.navigation import BACKWARD, FORWARD
from transkryptor.ui.notation_controller import IgnoredWarnings, NotationController
from transkryptor.ui.player_bar import PlayerBar
from transkryptor.ui.player_controller import PlayerController
from transkryptor.ui.readiness_dialog import ReadinessController
from transkryptor.ui.review import (
    DRAFT_APPEND,
    DRAFT_REPLACE,
    ReviewController,
    ask_draft_placement,
    draft_placement_box,
)
from transkryptor.ui.rules_store import RulesStore
from transkryptor.ui.search_bar import SearchBar
from transkryptor.ui.search_controller import SearchController
from transkryptor.ui.session import SessionController
from transkryptor.ui.settings_dialog import SettingsDialog
from transkryptor.ui.settings_store import SettingsStore
from transkryptor.ui.shortcuts import (
    ADD_COMMENT_ID,
    BASE_TOOLTIP,
    INSERT_TIMESTAMP,
    MARK_VERIFIED_ID,
    NEXT_COMMENT_ID,
    NEXT_UNCERTAIN_ID,
    NEXT_UNVERIFIED_ID,
    PLAY_FROM_CURSOR,
    PREVIOUS_COMMENT_ID,
    PREVIOUS_UNCERTAIN_ID,
    SHORTCUT_ACTIONS_BY_ID,
    SUPERSCRIPT_ID,
    apply_shortcuts,
    effective_shortcuts,
    marker_id,
    player_id,
    project_id,
    search_id,
)
from transkryptor.ui.snippets import SnippetController
from transkryptor.ui.speaker_controller import SpeakerController
from transkryptor.ui.sync_controller import SyncController
from transkryptor.ui.theme import apply_theme, resolve_tokens, set_props, tokens
from transkryptor.ui.toolbar import MainToolbar, ToolbarHandlers
from transkryptor.ui.update_controller import UpdateController
from transkryptor.ui.verification import VerificationController
from transkryptor.ui.warnings_panel import WarningsPanel
from transkryptor.ui.waveform import WaveformController, segment_spans

# Stałe przeniesione do kontrolerów, re-eksportowane dla zgodności importów.
__all__ = [
    "DRAFT_APPEND",
    "DRAFT_REPLACE",
    "MainWindow",
]

logger = logging.getLogger(__name__)

STATUS_MESSAGE_MS = 5000
# Pełna synchronizacja edytora z dokumentem (licznik słów, stan) po przerwie
# w pisaniu; zapis, eksport i walidacja synchronizują od razu.
SYNC_DEBOUNCE_MS = 300
WINDOW_TITLE = "Transkryptor"
RULE_ERRORS_SHOWN = 8


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
        # Prawa kolumna porównania wersji (tylko do odczytu, faza 14).
        self.compare_view = TranscriptionEditor()
        self.compare_view.setObjectName("compare_view")
        self.compare_view.setReadOnly(True)
        self.compare_view.setPlaceholderText("")
        self.search_bar = SearchBar()
        self.player_bar = PlayerBar(self.player, settings_store.current.player)
        self.audio_filters = AudioFilterController(self.player, self)
        self.warnings_panel = WarningsPanel()
        self.warnings_panel.set_warnings([])
        self.warning_count_label = label("", "badge")

        asr_settings = settings_store.current.asr
        self.asr_panel = AsrPanel(
            ModelManager(
                model_by_key(asr_settings.model_key),
                Path(asr_settings.models_root) if asr_settings.models_root else None,
            ),
            audio_path_provider=lambda: self.player.source_path,
            clip_provider=lambda: self.player_bar.loop_points(),
        )

        self.rules_store = RulesStore(parent=self)
        self.rules_store.load()
        self.asr_panel.set_rules(rule_infos(self.rules_store.rules))

        self.sync = SyncController(
            self.editor,
            self.player,
            self.player_bar,
            lambda: self.settings_store.current.player,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
            asr_settings=lambda: self.settings_store.current.asr,
        )
        self.review = ReviewController(
            self.editor,
            self.asr_panel,
            self,
            # Późne wiązanie: testy podmieniają ``_ask_draft_placement``.
            ask_placement=lambda: self._ask_draft_placement(),
            ellipsis_style=lambda: self._ellipsis_style,
            rules=lambda: self.rules_store.rules,
            sync=self.sync,
        )
        self.waveform = WaveformController(
            self.player,
            self.player_bar,
            self.sync.manual_times_ms,
            self._on_waveform_expanded,
            self,
        )
        self.ignored_warnings = IgnoredWarnings(self.editor)
        self.comments = CommentsController(
            self.editor,
            self.sync,
            self._comment_author,
            self._remember_comment_author,
            # Późne wiązanie: sesja powstaje niżej.
            lambda: self.session.comments_changed(),
            self,
            show_status=lambda text: self.statusBar().showMessage(
                text, STATUS_MESSAGE_MS
            ),
        )
        self.verification = VerificationController(
            self.editor,
            self.player,
            self.player_bar,
            self.sync,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
        )
        self.session = SessionController(
            self,
            self.editor,
            self.player,
            self.player_bar,
            self.asr_panel,
            self.review,
            self.ignored_warnings,
            self.sync,
            self.comments,
            self.verification,
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
            anchors=self.sync.entries,
            comments=self.comments.entries,
            audio_path=lambda: self.player.source_path,
            settings=lambda: self.settings_store.current.export,
            save_settings=self._save_export_settings,
            font_family=lambda: text_font_family(
                self.settings_store.current.editor.font_family
            ),
            # Późne wiązanie: kontroler notacji powstaje niżej.
            confirm=lambda: self.readiness.confirm_export(),
        )
        self.compare = CompareController(
            self.editor,
            self.compare_view,
            self._show_compare_column,
            self.sync,
            lambda: self.document,
            self._add_compared_speakers,
            lambda: self.session.audio_sha256,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
        )
        self.session.before_replace = self.compare.finish
        self.corpus = CorpusController(
            self.session,
            self.editor,
            self.player,
            lambda: self.settings_store.current.metadata.fields,
            self.settings_store.recent_projects,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
        )
        self.search = SearchController(
            self.editor, self.search_bar, self, self._informant_spans
        )
        self.speakers = SpeakerController(
            self.editor,
            lambda: self.document,
            self.metadata_form,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
        )
        self.notation = NotationController(
            self.editor,
            self.warnings_panel,
            self.warning_count_label,
            lambda: self.document,
            lambda: self._ellipsis_style,
            lambda text: self.statusBar().showMessage(text, STATUS_MESSAGE_MS),
            self,
            enabled_rules=lambda: self.settings_store.current.validator.enabled,
            ignored=self.ignored_warnings,
        )
        self._validation_timer = self.notation.timer
        self.readiness = ReadinessController(
            self,
            self._readiness_report,
            self.notation.go_to_range,
            self.metadata_form.focus_field,
            lambda: self.settings_store.current.export.readiness_check,
            self._set_readiness_check,
        )
        self.learning = RuleLearningController(
            self.editor,
            self.sync,
            lambda: self.document,
            lambda: self.rules_store.rules,
            self._on_learned_rule,
            self,
        )
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(SYNC_DEBOUNCE_MS)
        self._sync_timer.timeout.connect(self._update_title)
        self._sync_timer.timeout.connect(self.comments.refresh)

        self._build_layout()
        # Bez połączeń sieciowych przy tworzeniu okna: sprawdzanie startuje
        # punkt wejścia (``__main__.main``) przez ``updates.start_automatic``.
        self.updates = UpdateController(self)
        self._build_toolbar()
        self.player_controller = PlayerController(
            self,
            self.player,
            self.player_bar,
            {
                PLAY_FROM_CURSOR: self.sync.play_from_cursor,
                INSERT_TIMESTAMP: self.sync.insert_timestamp,
            },
        )
        self.player_actions = self.player_controller.actions
        self.search_actions = self.search.create_actions(self)
        self.speaker_actions = self.speakers.create_actions(self)
        self.review_actions = self._create_review_actions()
        self.snippets = SnippetController(
            self, self.editor, self.main_toolbar.snippets_menu, self._on_settings
        )
        self.shortcut_actions = self._collect_shortcut_actions()
        self._build_status_bar()
        self.loading_overlay = LoadingOverlay(self)
        self._connect_signals()
        self._apply_settings(settings_store.current)
        self.speakers.refresh()
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
        self.compare_title = shrinkable(label("", "muted"))
        self.compare_card = card(
            header_row(
                (16, 10, 12, 10),
                label(tr("compare.column"), "section"),
                self.compare_title,
            ),
            self.compare_view,
            stretch_index=0,
        )
        self.compare_card.hide()
        self.compare_columns = columns = QSplitter(Qt.Orientation.Horizontal)
        columns.setChildrenCollapsible(False)
        columns.setHandleWidth(12)
        columns.addWidget(editor_card)
        columns.addWidget(self.compare_card)

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
        splitter.addWidget(columns)
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
        self.compare_dock = side_dock(
            self, tr("compare.dock"), "compare_dock", self.compare.panel
        )
        self.tabifyDockWidget(self.asr_dock, self.compare_dock)
        self.comments_dock = side_dock(
            self, tr("comments.dock"), "comments_dock", self.comments.panel
        )
        self.tabifyDockWidget(self.asr_dock, self.comments_dock)
        self.asr_dock.raise_()
        self.compare_dock.hide()
        # Zamknięcie doku kończy porównanie (kolumna nie zostaje bez listy).
        self.compare_dock.visibilityChanged.connect(self._on_compare_dock_visibility)

    def _build_toolbar(self) -> None:
        bar = MainToolbar(
            self,
            self.asr_dock.toggleViewAction(),
            comments_toggle=self.comments_dock.toggleViewAction(),
            handlers=ToolbarHandlers(
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
                compare=self.compare.compare_dialog,
                corpus=self.corpus.open_dialog,
                export_anonymized=lambda: self.exporter.export(anonymize=True),
                export_as=self.exporter.export_as,
                readiness=self.readiness.show,
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
        self.export_as_action = bar.export_as_action
        self.readiness_action = bar.readiness_action
        self.close_action = bar.close_action
        self.open_action = bar.open_action
        self.save_action = bar.save_action
        self.save_as_action = bar.save_as_action
        self.import_docx_action = bar.import_docx_action
        self.compare_action = bar.compare_action
        self.corpus_action = bar.corpus_action
        self.main_toolbar = bar

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        # Lewy dolny róg: historia zmian. Na czas krótkiego komunikatu
        # (``showMessage``) pasek stanu chowa przycisk i pokazuje tekst.
        self.changelog_button = QToolButton()
        self.changelog_button.setObjectName("changelog_button")
        self.changelog_button.setText(tr("changelog.button", version=__version__))
        self.changelog_button.setToolTip(tr("changelog.button.tooltip"))
        self.changelog_button.setAutoRaise(True)
        self.changelog_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        icons.set_icon(self.changelog_button, "info", "text_muted", "text_muted")
        self.changelog_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.changelog_button.clicked.connect(self._on_changelog)
        status.addWidget(self.changelog_button)
        # Obok: formularz zgłoszeń na stronie - bez konta na GitHubie.
        self.report_button = QToolButton()
        self.report_button.setObjectName("report_button")
        self.report_button.setText(tr("report.button"))
        self.report_button.setToolTip(tr("report.button.tooltip"))
        self.report_button.setAutoRaise(True)
        self.report_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        icons.set_icon(self.report_button, "comment", "text_muted", "text_muted")
        self.report_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.report_button.clicked.connect(self._on_report)
        status.addWidget(self.report_button)
        # Propozycja reguły z powtarzalnych poprawek szkicu (ukryta bez niej).
        status.addPermanentWidget(self.learning.button)
        self.export_status_label = QLabel()
        status.addPermanentWidget(self.export_status_label)

    def _on_changelog(self) -> None:
        ChangelogDialog(self).exec()

    def _on_report(self) -> None:
        QDesktopServices.openUrl(QUrl(report_form_url()))

    def _connect_signals(self) -> None:
        self.editor.document().contentsChanged.connect(self._on_editor_changed)
        self.author_edit.textChanged.connect(self._on_metadata_changed)
        self.date_edit.dateChanged.connect(self._on_metadata_changed)
        self.metadata_form.changed.connect(self._on_metadata_changed)
        self.player_bar.import_requested.connect(self._on_import_audio)
        self.player_bar.sound_changed.connect(self._on_sound_changed)
        self.player_bar.media_available_changed.connect(
            lambda _available: self.audio_filters.refresh()
        )
        self.audio_filters.status_changed.connect(self.player_bar.set_sound_status)
        self.settings_store.settings_changed.connect(self._apply_settings)
        self.rules_store.rules_changed.connect(
            lambda: self.asr_panel.set_rules(rule_infos(self.rules_store.rules))
        )
        self.rules_store.rules_changed.connect(self.learning.refresh)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            # Motyw „zgodny z systemem” podąża za przełączeniem trybu systemu.
            app.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)
        self.asr_panel.seek_requested.connect(self.player_controller.seek_to_segment)
        self.asr_panel.model_changed.connect(self._on_asr_model_changed)
        self.asr_panel.speakers_changed.connect(self._on_asr_speakers_changed)
        self.asr_panel.context_changed.connect(self._on_asr_context_changed)
        self.sync.timestamps_edited.connect(self.session.project_data_changed)
        self.speakers.speakers_changed.connect(self._on_speakers_changed)
        self.sync.anchors_changed.connect(self.waveform.refresh_markers)
        self.verification.edited.connect(self.session.project_data_changed)
        self.verification.ranges_changed.connect(
            lambda: self.waveform.set_verified(self.verification.ranges)
        )
        self.asr_panel.result_changed.connect(self._on_asr_result_changed)
        self.player.playback_error.connect(
            lambda error: self._show_error(tr("main.playback_error"), error)
        )
        self.asr_panel.draft_ready.connect(self._on_draft_ready)
        self.asr_panel.fragment_ready.connect(self._on_fragment_ready)
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
        dialog = self.create_settings_dialog()
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.accept_settings_dialog(dialog)

    def create_settings_dialog(self) -> SettingsDialog:
        return SettingsDialog(
            self.settings_store.current,
            self,
            builtin_rules=self.rules_store.builtin,
            user_rules=self.rules_store.user_rules,
            document_text=self.editor.plain_text(),
            model_manager=self.asr_panel.manager,
        )

    def _on_learned_rule(self, rule: PhoneticRule) -> None:
        """Ustawienia na zakładce reguł z regułą zaproponowaną z poprawek."""
        dialog = self.create_settings_dialog()
        dialog.open_rules_with(rule)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.accept_settings_dialog(dialog)

    def accept_settings_dialog(self, dialog: SettingsDialog) -> None:
        """Zapisuje ustawienia i - gdy się zmieniły - reguły użytkownika."""
        user_rules = dialog.user_rules()
        if user_rules != self.rules_store.user_rules:
            try:
                self.rules_store.save_user_rules(user_rules)
            except AppError as error:
                self._show_error(tr("settings.rules.save_error"), error)
        self.settings_store.save(dialog.settings())

    def report_rule_errors(self) -> None:
        """ACC-42: błędne reguły z pliku użytkownika - komunikat przy starcie."""
        errors = self.rules_store.errors
        if not errors:
            return
        logger.warning("User rules file has %d invalid rule(s)", len(errors))
        lines = [error.message for error in errors[:RULE_ERRORS_SHOWN]]
        if len(errors) > RULE_ERRORS_SHOWN:
            lines.append(tr("rules.errors.more", count=len(errors) - RULE_ERRORS_SHOWN))
        QMessageBox.warning(
            self,
            tr("rules.errors.title"),
            tr("rules.errors.text", path=str(self.rules_store.path))
            + "\n\n"
            + "\n".join(lines),
        )

    def _apply_settings(self, settings: Settings) -> None:
        """Stosuje ustawienia do komponentów bez restartu (ACC-17)."""
        self._apply_theme(settings.appearance.theme)
        self.player_bar.apply_settings(settings.player)
        self.audio_filters.set_filters(settings.player.audio_filters)
        self.waveform.panel.set_expanded(settings.player.waveform_visible)
        self.editor.apply_settings(settings.editor)
        self.compare_view.apply_settings(settings.editor)
        self.metadata_form.set_fields(settings.metadata.fields)
        self.session.autosave.configure(settings.project)
        self.asr_panel.set_segment_preroll_ms(settings.player.segment_preroll_ms)
        self.asr_panel.set_asr_settings(settings.asr)
        self.sync.update_uncertain()
        # ACC-25: tekst się nie zmienia - tylko kolejne wstawienia i walidacja.
        pause_marker = marker_text("pause", settings.notation.ellipsis).strip()
        self.marker_actions["pause"].setProperty(
            BASE_TOOLTIP, tr("toolbar.insert", marker=pause_marker)
        )
        self._apply_shortcuts(effective_shortcuts(settings.shortcuts.overrides))
        self.snippets.set_snippets(settings.snippets.snippets)
        self.snippets.set_autocomplete(settings.editor.autocomplete)
        self.notation.schedule_validation()

    def _collect_shortcut_actions(self) -> dict[str, QAction]:
        """Akcje okna według identyfikatorów z ``SHORTCUT_ACTIONS``."""
        actions: dict[str, QAction] = {
            SUPERSCRIPT_ID: self.superscript_action,
            project_id("new"): self.new_action,
            project_id("open"): self.open_action,
            project_id("save"): self.save_action,
            project_id("save_as"): self.save_as_action,
            project_id("export"): self.export_action,
            project_id("settings"): self.settings_action,
            project_id("close"): self.close_action,
            project_id("corpus"): self.corpus_action,
        }
        for key, action in self.marker_actions.items():
            actions[marker_id(key)] = action
        for key, action in self.player_actions.items():
            actions[player_id(key)] = action
        for key, action in self.search_actions.items():
            actions[search_id(key)] = action
        actions.update(self.speaker_actions)
        actions[ADD_COMMENT_ID] = self.comments.add_action
        actions.update(self.review_actions)
        return actions

    def _create_review_actions(self) -> dict[str, QAction]:
        """Przejścia po niepewnych słowach i komentarzach oraz postęp weryfikacji."""
        actions: dict[str, QAction] = {
            MARK_VERIFIED_ID: self.verification.mark_action,
            NEXT_UNVERIFIED_ID: self.verification.next_action,
        }
        handlers = {
            NEXT_UNCERTAIN_ID: lambda: self.sync.go_to_uncertain(FORWARD),
            PREVIOUS_UNCERTAIN_ID: lambda: self.sync.go_to_uncertain(BACKWARD),
            NEXT_COMMENT_ID: lambda: self.comments.go_to(FORWARD),
            PREVIOUS_COMMENT_ID: lambda: self.comments.go_to(BACKWARD),
        }
        for action_id, handler in handlers.items():
            action = QAction(SHORTCUT_ACTIONS_BY_ID[action_id].label, self)
            action.triggered.connect(lambda _checked=False, run=handler: run())
            self.addAction(action)
            actions[action_id] = action
        return actions

    def _apply_shortcuts(self, shortcuts: dict[str, tuple[str, ...]]) -> None:
        """ACC-43: nowe skróty i podpowiedzi działają od razu, bez restartu."""
        for action_id, action in self.shortcut_actions.items():
            apply_shortcuts(action, shortcuts.get(action_id, ()))
        self.player_bar.apply_shortcuts(
            {key: shortcuts.get(player_id(key), ()) for key in self.player_actions}
        )
        self.search_bar.apply_shortcuts(
            shortcuts.get(search_id("find_next"), ()),
            shortcuts.get(search_id("find_previous"), ()),
        )

    def _on_asr_model_changed(self, key: str) -> None:
        """Wybór modelu w panelu jest zapamiętywany w ustawieniach (ACC-35)."""
        current = self.settings_store.current
        if current.asr.model_key != key:
            self.settings_store.save(
                replace(current, asr=replace(current.asr, model_key=key))
            )

    def _on_asr_speakers_changed(self, count: int) -> None:
        """Liczba mówców wybrana w panelu ASR jest zapamiętywana w ustawieniach."""
        current = self.settings_store.current
        if current.asr.diarize_speakers != count:
            self.settings_store.save(
                replace(current, asr=replace(current.asr, diarize_speakers=count))
            )

    def _readiness_report(self) -> ReadinessReport:
        """Raport gotowości z bieżącego tekstu (walidacja bez debounce)."""
        document = self.document
        self.notation.run_validation()
        return build_report(
            document.text,
            self.notation.warnings,
            self.sync.uncertain_ranges(),
            self.comments.entries(),
            document.paragraph_speakers,
            document.metadata,
            self.settings_store.current.metadata.fields,
        )

    def _set_readiness_check(self, enabled: bool) -> None:
        current = self.settings_store.current
        self._save_export_settings(replace(current.export, readiness_check=enabled))

    def _save_export_settings(self, export: ExportSettings) -> None:
        """Ostatni format i opcje okna „Eksportuj jako…” są pamiętane."""
        current = self.settings_store.current
        if current.export != export:
            self.settings_store.save(replace(current, export=export))

    def _on_waveform_expanded(self, expanded: bool) -> None:
        """Zwinięcie fali jest zapamiętywane w ustawieniach."""
        current = self.settings_store.current
        if current.player.waveform_visible != expanded:
            self.settings_store.save(
                replace(
                    current, player=replace(current.player, waveform_visible=expanded)
                )
            )

    def _on_sound_changed(self) -> None:
        """Głośność i filtry z menu „Dźwięk” są zapamiętywane w ustawieniach."""
        current = self.settings_store.current
        player = self.player_bar.sound_settings(current.player)
        if player != current.player:
            self.settings_store.save(replace(current, player=player))

    def _on_asr_result_changed(self) -> None:
        result = self.asr_panel.last_result
        self.waveform.set_segments(
            segment_spans(result.segments) if result is not None else []
        )

    def _on_asr_context_changed(self) -> None:
        self.session.asr_context_changed()

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
        self.sync.refresh_theme()
        self.waveform.view.update()
        # Ikony listy ostrzeżeń powstają przy walidacji.
        self.notation.schedule_validation()

    def _on_superscript(self) -> None:
        # ``mergeCharFormat`` emituje ``contentsChanged`` - synchronizacja
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
        self.speakers.refresh()
        self._update_title()

    def _on_session_state_changed(self) -> None:
        """Projekt otwarty, zapisany, odzyskany albo zaimportowany."""
        self.speakers.refresh()
        self._update_title()
        self.notation.schedule_validation()

    def _on_speakers_changed(self) -> None:
        self._update_title()
        self.notation.schedule_validation()

    def _informant_spans(self) -> list[tuple[int, int]]:
        document = self.document
        return informant_spans(
            document.text, document.paragraph_speakers, document.speakers
        )

    def _on_import_audio(self, path: str) -> None:
        self.session.import_audio(path)

    def _comment_author(self) -> str:
        """Podpis komentarzy: zapamiętany, a za pierwszym razem autor transkrypcji."""
        return (
            self.settings_store.current.review.comment_author
            or self.author_edit.text().strip()
        )

    def _remember_comment_author(self, author: str) -> None:
        current = self.settings_store.current
        self.settings_store.save(
            replace(current, review=replace(current.review, comment_author=author))
        )

    def _show_compare_column(self, name: str | None) -> None:
        """Kolumna i lista porównania z nazwą projektu (None - schowane)."""
        self.compare_card.setVisible(name is not None)
        if name is not None:
            # Obie wersje równej szerokości.
            half = max(self.compare_columns.width() // 2, 1)
            self.compare_columns.setSizes([half, half])
            self.compare_title.setText(name)
            self.compare_dock.show()
            self.compare_dock.raise_()
        else:
            self.compare_dock.hide()

    def _on_compare_dock_visibility(self, visible: bool) -> None:
        # Dok schowany za zakładką ASR też jest „niewidoczny” - porównanie
        # kończy dopiero zamknięcie doku.
        if not visible and self.compare_dock.isHidden() and self.compare.active:
            self.compare.finish()

    def _add_compared_speakers(self, missing: list[Speaker]) -> None:
        self.speakers.apply_speakers([*self.document.speakers, *missing])

    def _on_draft_ready(self, draft: TranscriptionResult | str) -> None:
        self.compare.finish()
        if not isinstance(draft, TranscriptionResult):
            self.review.insert_draft(draft)
            return
        if not draft.diarized:
            self.review.insert_draft(draft_text(draft), draft.segments)
            return
        # Podział na mówców: głosy w kolejności pojawiania się dostają
        # kolejnych mówców z listy (B, I, a brakujący - I2, I3…).
        clusters = draft_line_speakers(draft)
        count = 1 + max(
            (number for number in clusters if number is not None), default=0
        )
        previous = list(self.document.speakers)
        speakers, keys = speakers_for_clusters(previous, count)
        if list(speakers) != previous:
            self.speakers.apply_speakers(list(speakers))
        line_speakers = [
            None if number is None else keys[number] for number in clusters
        ]
        if (
            not self.review.insert_draft(
                draft_text(draft), draft.segments, line_speakers
            )
            and list(speakers) != previous
        ):
            self.speakers.apply_speakers(previous)

    def _on_fragment_ready(self, result: TranscriptionResult) -> None:
        self.compare.finish()
        self.review.insert_fragment(result.text, result.segments)

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
        # Wyszukiwanie w korpusie ma przycisk „Przerwij” - okno czeka na nie.
        if self.corpus.busy:
            event.ignore()
            return
        if self.session.can_close():
            self.waveform.shutdown()
            self.audio_filters.shutdown()
            self.corpus.shutdown()
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
            self.compare_action,
            self.corpus_action,
            self.comments.add_action,
            *(
                action
                for action_id, action in self.review_actions.items()
                if action_id not in (MARK_VERIFIED_ID, NEXT_UNVERIFIED_ID)
            ),
            self.export_action,
            self.export_anonymized_action,
            self.export_as_action,
            self.readiness_action,
            self.settings_action,
            self.unify_ellipses_action,
            *self.search_actions.values(),
        ):
            action.setEnabled(not locked)
        self.player_controller.set_locked(locked)
        self.snippets.set_locked(locked)
        self.speakers.set_locked(locked)
        self.verification.set_locked(locked)
        self.corpus.set_locked(locked)
        self.learning.set_locked(locked)

    # --- stan --------------------------------------------------------------

    def _update_title(self) -> None:
        """Odświeża tytuł okna, licznik słów i stan eksportu w pasku stanu.

        Gwiazdka w tytule: niezapisane zmiany projektu, a bez pliku
        projektu - niewyeksportowane zmiany.
        """
        self._sync_timer.stop()
        document = self.document
        words = len(document.text.split())
        text = f"{words} {words_label(words)}"
        uses_speakers = bool(document.paragraph_speakers)
        if uses_speakers:
            informant_words = sum(
                len(document.text[start:end].split())
                for start, end in self._informant_spans()
            )
            text = tr("main.words_informant", words=text, informant=informant_words)
        self.word_count_label.setText(text)
        self.search_bar.set_informant_filter_available(uses_speakers)
        # Cofnięcie przypisania mówcy zmienia tylko format bloku.
        self.editor.refresh_speakers()
        self._show_dirty_state(self.session.has_unsaved_work, document.is_dirty)

    def _show_dirty_state(self, unsaved: bool, dirty: bool) -> None:
        """Gwiazdka w tytule i stan eksportu w pasku stanu."""
        marker = "*" if unsaved else ""
        name = self.session.project_name
        self.setWindowTitle(
            f"{WINDOW_TITLE} - {name}{marker}" if name else f"{WINDOW_TITLE}{marker}"
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
