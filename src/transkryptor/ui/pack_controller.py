"""Paczka do przekazania w oknie: eksport, otwarcie i przeciągnięcie pliku.

„Eksportuj paczkę…” zbiera projekt (z czekaniem na sumę nagrania),
nagranie, reguły fonetyczne użytkownika, wstawki, ustawienia notacji
i szablon DOCX z ustawień eksportu, pokazuje zawartość i rozmiar
(``ui/pack_dialogs.py``) i zapisuje plik ``.tkpack`` (``document/pack.py``).

„Otwórz paczkę…” (i upuszczenie pliku ``.tkpack`` na okno) rozpakowuje
paczkę do wskazanego katalogu, pyta o ustawienia z paczki
(``document/pack_settings.py``) i otwiera projekt zwykłą ścieżką sesji -
paczka bez nagrania wiąże je jak każdy projekt: po sumie SHA-256.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction, QDropEvent
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from transkryptor.document.metadata import SIGNATURE
from transkryptor.document.pack import (
    PACK_SUFFIX,
    PackManifest,
    PackSettings,
    PackSource,
    conflicts,
    file_dialog_filter,
    open_pack,
    read_manifest,
    write_pack,
)
from transkryptor.document.pack_settings import apply_pack_settings
from transkryptor.document.project import PROJECT_SUFFIX
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.notation.rules import dumps_rules
from transkryptor.settings import Settings
from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.messages import show_error
from transkryptor.ui.pack_dialogs import PackExportDialog, PackImportDialog
from transkryptor.ui.rules_store import RulesStore
from transkryptor.ui.session import SessionController
from transkryptor.ui.settings_store import SettingsStore

_DROP_EVENTS = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)


def pack_in(urls: list[Path]) -> Path | None:
    """Pierwszy plik paczki wśród upuszczonych plików."""
    return next((p for p in urls if p.suffix.lower() == PACK_SUFFIX), None)


class PackController(QObject):
    """Polecenia paczki i upuszczanie pliku ``.tkpack`` na okno."""

    def __init__(
        self,
        window: QWidget,
        session: SessionController,
        settings_store: SettingsStore,
        rules_store: RulesStore,
        audio_path: Callable[[], Path | None],
        show_status: Callable[[str], None],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._session = session
        self._settings_store = settings_store
        self._rules_store = rules_store
        self._audio_path = audio_path
        self._show_status = show_status
        self.export_action = QAction(tr("pack.export"), window)
        self.export_action.setToolTip(tr("pack.export.tooltip"))
        self.export_action.triggered.connect(lambda _checked=False: self.export())
        self.open_action = QAction(tr("pack.open"), window)
        self.open_action.setToolTip(tr("pack.open.tooltip"))
        self.open_action.triggered.connect(lambda _checked=False: self.open_dialog())
        self.actions = (self.export_action, self.open_action)
        # Okna dialogowe; testy podstawiają gotowe odpowiedzi.
        self.run_export_dialog: Callable[[PackExportDialog], int] = lambda d: d.exec()
        self.run_import_dialog: Callable[[PackImportDialog], int] = lambda d: d.exec()
        self.choose_directory: Callable[[Path], Path | None] = self._choose_directory
        self._locked = False
        self.accept_drops_on(window)

    def accept_drops_on(self, *widgets: QWidget) -> None:
        """Upuszczenie paczki na ``widgets`` (np. widok edytora) ją otwiera.

        Filtr zdarzeń tylko na tych widżetach - nie na całej aplikacji.
        """
        for widget in widgets:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        for action in self.actions:
            action.setEnabled(not locked)

    # --- eksport ---------------------------------------------------------

    def source(self) -> PackSource:
        """Bieżąca praca i ustawienia notacji jako zawartość paczki."""
        self._session.wait_for_audio_hash()
        settings = self._settings_store.current
        user_rules = self._rules_store.user_rules
        template = settings.export.template_path
        return PackSource(
            state=self._session.capture_state(),
            project_name=self._project_name(),
            audio_path=self._audio_path(),
            settings=PackSettings(
                rules_toml=dumps_rules(user_rules) if user_rules else "",
                snippets_spec=settings.snippets.spec,
                ellipsis_style=settings.notation.ellipsis_style,
                validator_spec=settings.validator.overrides_spec,
            ),
            template_path=Path(template) if template else None,
        )

    def export(self) -> Path | None:
        """„Eksportuj paczkę…”; zwraca zapisany plik (None - anulowano/błąd)."""
        dialog = PackExportDialog(self.source(), self._window)
        if self.run_export_dialog(dialog) != PackExportDialog.DialogCode.Accepted:
            return None
        source = dialog.source()
        target = ask_save_path(
            self._window,
            tr("pack.export.dialog"),
            self._default_pack_path(),
            file_dialog_filter(),
            PACK_SUFFIX,
        )
        if target is None:
            return None
        try:
            write_pack(target, source)
        except AppError as error:
            show_error(self._window, tr("pack.export.error"), error)
            return None
        self._show_status(tr("pack.export.done", name=target.name))
        return target

    def _project_name(self) -> str:
        if self._session.project_name:
            return self._session.project_name
        signature = self._session.document.metadata.get(SIGNATURE, "").strip()
        audio = self._audio_path()
        stem = signature or (
            audio.stem if audio else tr("session.default_project_name")
        )
        return f"{stem}{PROJECT_SUFFIX}"

    def _default_pack_path(self) -> str:
        """Obok projektu, a bez pliku projektu - obok nagrania.

        Sama nazwa pliku otworzyłaby okno w katalogu bieżącym procesu,
        a paczka trafiłaby tam, gdzie użytkownik jej nie szuka.
        """
        name = f"{Path(self._project_name()).stem}{PACK_SUFFIX}"
        anchor = self._session.project_path or self._audio_path()
        if anchor is not None:
            return str(anchor.parent / name)
        return name

    # --- otwieranie ------------------------------------------------------

    def open_dialog(self) -> bool:
        if not self._session.maybe_discard_changes():
            return False
        path, _selected = QFileDialog.getOpenFileName(
            self._window, tr("pack.open.dialog"), "", file_dialog_filter()
        )
        return bool(path) and self.open_pack(Path(path), confirm=False)

    def open_pack(self, path: Path, confirm: bool = True) -> bool:
        """Rozpakowuje paczkę, stosuje wybrane ustawienia i otwiera projekt."""
        if confirm and not self._session.maybe_discard_changes():
            return False
        try:
            manifest = read_manifest(path)
        except AppError as error:
            show_error(self._window, tr("pack.open.error"), error)
            return False
        directory = self.choose_directory(path.parent)
        if directory is None or not self._confirm_overwrite(manifest, directory):
            return False
        try:
            opened = open_pack(path, directory)
        except AppError as error:
            show_error(self._window, tr("pack.open.error"), error)
            return False
        dialog = PackImportDialog(
            opened.manifest,
            opened.settings,
            opened.template_path is not None,
            self._window,
        )
        if self.run_import_dialog(dialog) != PackImportDialog.DialogCode.Accepted:
            return False
        self._apply_settings(opened.settings, dialog, opened.template_path)
        return self._session.open_project(opened.project_path, confirm=False)

    def _confirm_overwrite(self, manifest: PackManifest, directory: Path) -> bool:
        existing = conflicts(manifest, directory)
        if not existing:
            return True
        answer = QMessageBox.question(
            self._window,
            tr("pack.open.overwrite.title"),
            tr("pack.open.overwrite.text", files="\n".join(existing)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _apply_settings(
        self, pack: PackSettings, dialog: PackImportDialog, template: Path | None
    ) -> None:
        current = self._settings_store.current
        applied = apply_pack_settings(
            pack, dialog.choices(), current, self._rules_store.user_rules
        )
        settings: Settings = applied.settings
        if template is not None and dialog.use_template:
            settings = replace(
                settings,
                export=replace(settings.export, template_path=str(template)),
            )
        if applied.user_rules is not None:
            try:
                self._rules_store.save_user_rules(applied.user_rules)
            except AppError as error:
                show_error(self._window, tr("settings.rules.save_error"), error)
        if settings != current:
            self._settings_store.save(settings)

    def _choose_directory(self, start: Path) -> Path | None:
        """Katalog, do którego trafią pliki paczki (start: katalog paczki)."""
        chosen = QFileDialog.getExistingDirectory(
            self._window, tr("pack.open.directory"), str(start)
        )
        return Path(chosen) if chosen else None

    # --- przeciąganie pliku na okno --------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() not in _DROP_EVENTS or self._locked:
            return False
        if not isinstance(event, QDropEvent):  # też DragEnter i DragMove
            return False
        urls = event.mimeData().urls()
        dropped = pack_in([Path(url.toLocalFile()) for url in urls])
        if dropped is None:
            return False
        event.acceptProposedAction()
        if event.type() == QEvent.Type.Drop:
            self.open_pack(dropped)
        return True
