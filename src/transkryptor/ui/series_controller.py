"""Seria nagrań w oknie: import ZIP, folder nagrań i „Następne nagranie”.

„Importuj serię nagrań (ZIP)…” rozpakowuje nagrania z archiwum do folderu
o nazwie archiwum we wskazanym katalogu (``corpus/series.py``) - w wątku
w tle, z postępem i przerwaniem (``ui/series_import.py``) - i otwiera
pierwsze z nich. „Otwórz folder nagrań…” robi to samo dla folderu, który
już ma nagrania - otwiera pierwsze bez projektu, więc wznawia pracę.

„Następne nagranie serii” zapisuje bieżącą pracę - do jej projektu, a bez
niego do projektu obok nagrania (``project_for``) - i otwiera kolejne
nagranie folderu: jego projekt, gdy już jest, albo nową transkrypcję.
Przycisk serii w pasku stanu pokazuje numer nagrania i postęp serii;
jego menu pokazuje też folder serii w oknie „Korpus”, gdzie da się
przeglądać, przeszukiwać i zestawiać wszystkie transkrypcje naraz,
„Przygotuj szkice dla serii…” - kolejkę szkiców ASR wszystkich nagrań bez
szkicu (``ui/series_drafts.py``), „Przegląd serii” - tabelę stanu
wszystkich nagrań (``ui/series_overview_dialog.py``) - i „Eksportuj
serię…”: wszystkie projekty serii jednym zestawem opcji
(``ui/series_export.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)

from transkryptor.corpus.series import (
    ZIP_SUFFIX,
    SeriesImport,
    first_unfinished,
    project_for,
    series_position,
    series_recordings,
)
from transkryptor.corpus.series_overview import ReadinessOptions
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.settings import Settings
from transkryptor.ui import icons
from transkryptor.ui.asr_controller import AsrController
from transkryptor.ui.export_controller import ExportController
from transkryptor.ui.messages import show_error
from transkryptor.ui.series_drafts import SeriesDrafts
from transkryptor.ui.series_export import SeriesExporter
from transkryptor.ui.series_import import SeriesImporter
from transkryptor.ui.series_overview_dialog import SeriesOverviewDialog
from transkryptor.ui.session import SessionController


class SeriesController(QObject):
    """Polecenia serii nagrań i przycisk serii w pasku stanu."""

    def __init__(
        self,
        window: QWidget,
        session: SessionController,
        audio_path: Callable[[], Path | None],
        show_folder: Callable[[Path], object],
        show_status: Callable[[str], None],
        asr: Callable[[], AsrController],
        settings: Callable[[], Settings],
        exports: ExportController,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._session = session
        self._audio_path = audio_path
        self._show_folder = show_folder
        self._show_status = show_status
        self._settings = settings
        self._locked = False
        self.drafts = SeriesDrafts(
            window, session, asr, audio_path, self.open_recording
        )
        self.overview: SeriesOverviewDialog | None = None
        self.exporter = SeriesExporter(window, exports, settings, show_status)
        self.importer = SeriesImporter(window)
        self.importer.finished.connect(self._on_imported)
        self._build_actions()
        self._build_button()
        # Okna wyboru plików; testy podstawiają gotowe odpowiedzi.
        self.choose_archive: Callable[[], Path | None] = self._choose_archive
        self.choose_directory: Callable[[str, Path], Path | None] = (
            self._choose_directory
        )
        self.refresh()

    def _build_actions(self) -> None:
        window = self._window
        self.import_action = QAction(tr("series.import"), window)
        self.import_action.setToolTip(tr("series.import.tooltip"))
        self.import_action.triggered.connect(lambda _c=False: self.import_dialog())
        self.open_folder_action = QAction(tr("series.open_folder"), window)
        self.open_folder_action.setToolTip(tr("series.open_folder.tooltip"))
        self.open_folder_action.triggered.connect(lambda _c=False: self.folder_dialog())
        self.next_action = QAction(tr("series.next"), window)
        self.next_action.setToolTip(tr("series.next.tooltip"))
        self.next_action.triggered.connect(lambda _c=False: self.open_next())
        window.addAction(self.next_action)  # skrót działa bez przycisku
        self.corpus_action = QAction(tr("series.corpus"), window)
        self.corpus_action.setToolTip(tr("series.corpus.tooltip"))
        self.corpus_action.triggered.connect(lambda _c=False: self.show_in_corpus())
        self.drafts_action = QAction(tr("series.drafts"), window)
        self.drafts_action.setToolTip(tr("series.drafts.tooltip"))
        self.drafts_action.triggered.connect(lambda _c=False: self.prepare_drafts())
        self.overview_action = QAction(tr("series.overview"), window)
        self.overview_action.setToolTip(tr("series.overview.tooltip"))
        self.overview_action.triggered.connect(lambda _c=False: self.show_overview())
        self.export_action = QAction(tr("series.export"), window)
        self.export_action.setToolTip(tr("series.export.tooltip"))
        self.export_action.triggered.connect(lambda _c=False: self.export_series())
        # Polecenia menu „Otwórz”.
        self.open_actions = (self.import_action, self.open_folder_action)

    def _build_button(self) -> None:
        self.button = QToolButton()
        self.button.setObjectName("series_button")
        self.button.setAutoRaise(True)
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        icons.set_icon(self.button, "audio_file", "accent", "text_muted")
        self.button.clicked.connect(self.open_next)
        menu = QMenu(self.button)
        menu.addAction(self.next_action)
        menu.addAction(self.drafts_action)
        menu.addAction(self.overview_action)
        menu.addAction(self.export_action)
        menu.addAction(self.corpus_action)
        self.button.setMenu(menu)
        self.button.hide()
        events = self._session.events
        for signal in (events.state_changed, events.reset):
            signal.connect(self.refresh)

    # --- stan ------------------------------------------------------------

    def refresh(self) -> None:
        """Przycisk serii i dostępność poleceń dla bieżącego nagrania."""
        recording = self._audio_path()
        position = series_position(recording) if recording is not None else None
        self.button.setVisible(position is not None)
        has_next = position is not None and position.next_recording is not None
        self.next_action.setEnabled(has_next and not self._locked)
        self.corpus_action.setEnabled(position is not None and not self._locked)
        self.drafts_action.setEnabled(position is not None and not self._locked)
        self.overview_action.setEnabled(position is not None and not self._locked)
        self.export_action.setEnabled(position is not None and not self._locked)
        self.button.setEnabled(not self._locked)
        if position is None:
            return
        self.button.setText(
            tr("series.button", number=position.number, total=position.total)
        )
        following = position.next_recording
        self.button.setToolTip(
            tr(
                "series.button.tooltip",
                folder=str(recording.parent) if recording else "",
                done=position.done,
                total=position.total,
                next=following.name if following else tr("series.button.last"),
            )
        )

    @property
    def busy(self) -> bool:
        """Trwa rozpakowanie, kolejka szkiców albo eksport serii."""
        return self.importer.busy or self.drafts.busy or self.exporter.busy

    def on_media_available(self, _available: bool) -> None:
        self.refresh()

    def set_locked(self, locked: bool) -> None:
        """Na czas transkrypcji polecenia serii są nieaktywne."""
        self._locked = locked
        self.import_action.setEnabled(not locked)
        self.open_folder_action.setEnabled(not locked)
        if self.overview is not None:
            self.overview.setEnabled(not locked)
        self.refresh()

    # --- polecenia -------------------------------------------------------

    def import_dialog(self) -> bool:
        """„Importuj serię nagrań (ZIP)…”; True - rozpakowanie ruszyło.

        Pierwsze nagranie otwiera się po końcu rozpakowania w tle.
        """
        if self.busy or not self._session.maybe_discard_changes():
            return False
        archive = self.choose_archive()
        if archive is None:
            return False
        parent = self.choose_directory(tr("series.import.directory"), archive.parent)
        if parent is None:
            return False
        return self.importer.start(archive, parent / archive.stem)

    def _on_imported(
        self, result: SeriesImport | None, error: BaseException | None
    ) -> None:
        if error is not None:
            if not isinstance(error, AppError):
                raise error
            show_error(self._window, tr("series.import.error"), error)
            return
        if result is None:
            self._show_status(tr("series.import.cancelled"))
            return
        self._show_status(
            tr(
                "series.import.done",
                count=len(result.recordings),
                folder=result.folder.name,
            )
        )
        if result.skipped:
            QMessageBox.information(
                self._window,
                tr("series.import.skipped.title"),
                tr("series.import.skipped.text", files="\n".join(result.skipped)),
            )
        self._open_first(list(result.recordings))

    def folder_dialog(self) -> bool:
        """„Otwórz folder nagrań…”: pierwsze nagranie bez projektu."""
        if not self._session.maybe_discard_changes():
            return False
        start = Path(self._session.save_location.start_dir())
        folder = self.choose_directory(tr("series.open_folder.dialog"), start)
        if folder is None:
            return False
        recordings = series_recordings(folder)
        if not recordings:
            QMessageBox.information(
                self._window,
                tr("series.open_folder.empty.title"),
                tr("series.open_folder.empty.text", folder=str(folder)),
            )
            return False
        return self._open_first(recordings)

    def open_next(self) -> bool:
        """Zapisuje bieżącą pracę i otwiera następne nagranie serii."""
        if self._locked:
            return False
        recording = self._audio_path()
        position = series_position(recording) if recording is not None else None
        if recording is None or position is None or position.next_recording is None:
            self._show_status(tr("series.next.none"))
            return False
        if not self._save_current(recording):
            return False
        return self.open_recording(position.next_recording)

    def prepare_drafts(self) -> bool:
        """„Przygotuj szkice dla serii…”: kolejka dla folderu bieżącego nagrania."""
        recording = self._audio_path()
        if self._locked or recording is None:
            return False
        return self.drafts.start(recording.parent)

    def show_in_corpus(self) -> None:
        recording = self._audio_path()
        if recording is not None:
            self._show_folder(recording.parent)

    def show_overview(self) -> SeriesOverviewDialog | None:
        """„Przegląd serii”: tabela stanu nagrań folderu bieżącego nagrania."""
        recording = self._audio_path()
        if recording is None:
            return None
        dialog = self.overview
        if dialog is not None and dialog.folder != recording.parent:
            dialog.close()
            dialog.deleteLater()
            dialog = None
        if dialog is None:
            dialog = self.overview = SeriesOverviewDialog(
                recording.parent,
                lambda: ReadinessOptions.from_settings(self._settings()),
                self._window,
            )
            dialog.open_requested.connect(self._open_from_overview)
        else:
            dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def export_series(self) -> bool:
        """„Eksportuj serię…”: projekty folderu bieżącego nagrania."""
        recording = self._audio_path()
        if self._locked or recording is None:
            return False
        return self.exporter.start(recording.parent)

    def shutdown(self) -> None:
        """Zamyka przegląd serii (przerywa wczytywanie w tle)."""
        if self.overview is not None:
            self.overview.close()

    def _open_from_overview(self, recording: Path) -> None:
        """Dwuklik w przeglądzie: nagranie serii (pyta o niezapisane zmiany)."""
        if self._locked or not self._session.maybe_discard_changes():
            return
        if self.open_recording(recording) and self.overview is not None:
            self.overview.refresh()

    def open_recording(self, recording: Path) -> bool:
        """Projekt nagrania z folderu serii, a bez niego - nowa transkrypcja.

        Nie pyta o niezapisane zmiany - wołający już o nie zadbał.
        """
        project = project_for(recording, series_recordings(recording.parent))
        if project.is_file():
            opened = self._session.open_project(project, confirm=False)
        else:
            self._session.new_document(confirm=False)
            self._session.import_audio(str(recording))
            current = self._audio_path()
            opened = current is not None and current.resolve() == recording.resolve()
        self.refresh()
        position = series_position(recording)
        if opened and position is not None:
            self._show_status(
                tr(
                    "series.opened",
                    name=recording.name,
                    number=position.number,
                    total=position.total,
                )
            )
        return opened

    # --- etapy -----------------------------------------------------------

    def _save_current(self, recording: Path) -> bool:
        """Bieżąca praca do jej projektu albo do projektu obok nagrania.

        Nietknięte nagranie bez projektu (sam podgląd) nie dostaje pliku -
        nie liczy się jako gotowe. Istniejący, nieotwarty projekt o nazwie
        nagrania nie jest nadpisywany bez pytania (okno „Zapisz jako”).
        """
        if self._session.project_path is not None:
            return self._session.save_project()
        if not self._session.has_unsaved_work:
            return True
        target = project_for(recording, series_recordings(recording.parent))
        if target.exists():
            return self._session.save_project_as()
        return self._session.write_project(target)

    def _open_first(self, recordings: list[Path]) -> bool:
        first = first_unfinished(recordings)
        return first is not None and self.open_recording(first)

    def _choose_archive(self) -> Path | None:
        path, _selected = QFileDialog.getOpenFileName(
            self._window,
            tr("series.import.dialog"),
            self._session.save_location.start_dir(),
            tr("series.import.filter", patterns=f"*{ZIP_SUFFIX}"),
        )
        return Path(path) if path else None

    def _choose_directory(self, title: str, start: Path) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(self._window, title, str(start))
        return Path(chosen) if chosen else None
