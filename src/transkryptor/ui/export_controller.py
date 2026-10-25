"""Eksport transkrypcji (REQ-07, REQ-08, REQ-24), także z anonimizacją.

DOCX to format główny (przycisk na pasku, ``Ctrl+E``); pozostałe formaty
z rejestru ``export/registry.py`` są w oknie „Eksportuj jako…”. Raport
eksportu (np. fragmenty z czasem interpolowanym) jest pokazywany po zapisie.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDateEdit, QMessageBox, QWidget

from transkryptor.document.anchors import Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.metadata import SIGNATURE, MetadataField
from transkryptor.document.model import Document
from transkryptor.errors import AppError
from transkryptor.export.model import build_export_document
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.registry import DOCX, Exporter, exporter_by_key, run_export
from transkryptor.i18n import tr
from transkryptor.settings import ExportSettings
from transkryptor.ui.export_dialog import ExportDialog
from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.messages import show_error

logger = logging.getLogger(__name__)

DOCX_SUFFIX = ".docx"


class ExportController(QObject):
    """Wybór pliku i formatu, zapis i oznaczenie dokumentu jako wyeksportowanego.

    Oznaczenie dotyczy tylko pełnego eksportu DOCX (nie anonimizowanego) -
    DOCX pozostaje głównym formatem pracy.
    """

    def __init__(
        self,
        dialog_parent: QWidget,
        document: Callable[[], Document],
        date_edit: QDateEdit,
        fields: Callable[[], tuple[MetadataField, ...]],
        on_exported: Callable[[], None],
        anchors: Callable[[], Iterable[Anchor]] = tuple,
        comments: Callable[[], Iterable[Comment]] = tuple,
        audio_path: Callable[[], Path | None] = lambda: None,
        settings: Callable[[], ExportSettings] = ExportSettings,
        save_settings: Callable[[ExportSettings], None] = lambda _settings: None,
        font_family: Callable[[], str] = str,
    ) -> None:
        super().__init__(dialog_parent)
        self._parent = dialog_parent
        self._document = document
        self._date_edit = date_edit
        self._on_exported = on_exported
        self._fields = fields
        self._anchors = anchors
        self._comments = comments
        self._audio_path = audio_path
        self._settings = settings
        self._save_settings = save_settings
        self._font_family = font_family
        self.last_report: ExportReport | None = None

    def export(self, anonymize: bool = False) -> None:
        """ACC-32: ``anonymize`` pomija pola metryczki oznaczone jako osobowe.

        Eksport anonimizowany nie oznacza dokumentu jako wyeksportowanego:
        pełna wersja (z danymi informatora) nadal nie powstała, więc
        ostrzeżenie ACC-10 zostaje.
        """
        settings = self._settings()
        self._export(
            exporter_by_key(DOCX),
            ExportOptions(
                superscript=settings.superscript_mode,
                untimed=settings.untimed_mode,
            ),
            anonymize,
        )

    def has_times(self) -> bool:
        return any(anchor.source != "word" for anchor in self._anchors())

    def create_dialog(self) -> ExportDialog:
        settings = self._settings()
        return ExportDialog(
            settings.last_format,
            settings.superscript_mode,
            settings.untimed_mode,
            self.has_times(),
            self._parent,
        )

    def export_as(self) -> None:
        """Okno „Eksportuj jako…”: format i opcje, potem plik."""
        dialog = self.create_dialog()
        if dialog.exec() != ExportDialog.DialogCode.Accepted:
            return
        self.export_with(dialog.exporter, dialog.options(), dialog.anonymize)

    def export_with(
        self, exporter: Exporter, options: ExportOptions, anonymize: bool
    ) -> bool:
        """Zapamiętuje wybór okna i eksportuje."""
        settings = self._settings()
        self._save_settings(
            replace(
                settings,
                last_format=exporter.key,
                superscript_mode=options.superscript,
                untimed_mode=options.untimed,
            )
        )
        return self._export(exporter, options, anonymize)

    def _export(
        self, exporter: Exporter, options: ExportOptions, anonymize: bool
    ) -> bool:
        document = self._document()
        if exporter.key == DOCX:
            title = tr("export.dialog.anonymized" if anonymize else "export.dialog")
            file_filter = tr("export.filter")
        else:
            title = tr(
                "export.dialog.as_anonymized" if anonymize else "export.dialog.as",
                format=exporter.label,
            )
            file_filter = exporter.file_filter
        path = ask_save_path(
            self._parent,
            title,
            self._default_name(document, anonymize, exporter.suffix),
            file_filter,
            exporter.suffix,
        )
        if path is None:
            return False
        logger.info(
            "Exporting %s: %d characters, anonymized=%s",
            exporter.key,
            len(document.text),
            anonymize,
        )
        options = replace(
            options,
            template_path=self._settings().template_path,
            font_family=self._font_family(),
        )
        try:
            export_document = build_export_document(
                document,
                self._fields(),
                anonymize,
                self._anchors() if exporter.timed else (),
                self._audio_path(),
                self._comments() if exporter.key == DOCX else (),
            )
            report = run_export(exporter, export_document, path, options)
        except AppError as error:
            show_error(self._parent, tr("export.error.title"), error)
            return False
        self.last_report = report
        if exporter.key == DOCX and not anonymize:
            document.mark_exported()
        self._on_exported()
        if report.warnings:
            QMessageBox.warning(
                self._parent,
                tr("export.report.title"),
                tr("export.report.text", name=path.name)
                + "\n\n"
                + "\n\n".join(report.warnings),
            )
        return True

    def _default_name(self, document: Document, anonymize: bool, suffix: str) -> str:
        base = document.metadata.get(SIGNATURE, "").strip() or tr(
            "export.default_name",
            date=self._date_edit.date().toString("yyyy-MM-dd"),
        )
        anonymized = tr("export.anonymized_suffix") if anonymize else ""
        return f"{base}{anonymized}{suffix}"
