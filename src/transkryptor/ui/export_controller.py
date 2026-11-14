"""Eksport transkrypcji (REQ-07, REQ-08, REQ-24), także z anonimizacją.

DOCX to format główny (przycisk na pasku, ``Ctrl+E``); pozostałe formaty
z rejestru ``export/registry.py`` są w oknie „Eksportuj jako…”. Przed
wyborem pliku ``confirm`` może zatrzymać eksport (raport gotowości do
oddania, ``ui/readiness_dialog.py``). Raport eksportu (np. fragmenty
z czasem interpolowanym) jest pokazywany po zapisie. Części mowy wybrane
w oknie dostają w pliku tło w swoim kolorze (zgłoszenie #54).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QDate, QObject
from PySide6.QtWidgets import QMessageBox, QWidget

from transkryptor.document.anchors import Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.metadata import SIGNATURE, MetadataField
from transkryptor.document.model import Document
from transkryptor.document.parts_of_speech import (
    PartOfSpeech,
    PartOfSpeechTagger,
    paper_color,
)
from transkryptor.errors import AppError
from transkryptor.export.model import (
    ExportDocument,
    build_export_document,
    with_highlights,
)
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.registry import (
    DOCX,
    OPTION_PARTS_OF_SPEECH,
    Exporter,
    exporter_by_key,
    run_export,
)
from transkryptor.i18n import tr
from transkryptor.settings import ExportSettings
from transkryptor.ui.export_dialog import ExportDialog
from transkryptor.ui.file_dialogs import ask_save_path
from transkryptor.ui.messages import show_error

logger = logging.getLogger(__name__)

DOCX_SUFFIX = ".docx"


@dataclass(frozen=True)
class ExportSources:
    """Dane projektu i edytora, z których powstaje plik (wąskie funkcje).

    ``pos_selected`` - części mowy podświetlane w edytorze (domyślny wybór
    okna), ``pos_tagger`` - analizator części mowy albo None, gdy
    niedostępny.
    """

    fields: Callable[[], tuple[MetadataField, ...]]
    anchors: Callable[[], Iterable[Anchor]] = tuple
    comments: Callable[[], Iterable[Comment]] = tuple
    audio_path: Callable[[], Path | None] = lambda: None
    font_family: Callable[[], str] = str
    pos_selected: Callable[[], tuple[PartOfSpeech, ...]] = tuple
    pos_tagger: Callable[[], PartOfSpeechTagger | None] = lambda: None


class ExportController(QObject):
    """Wybór pliku i formatu, zapis i oznaczenie dokumentu jako wyeksportowanego.

    Oznaczenie dotyczy tylko pełnego eksportu DOCX (nie anonimizowanego) -
    DOCX pozostaje głównym formatem pracy.
    """

    def __init__(
        self,
        dialog_parent: QWidget,
        document: Callable[[], Document],
        date: Callable[[], QDate],
        sources: ExportSources,
        on_exported: Callable[[], None],
        settings: Callable[[], ExportSettings] = ExportSettings,
        save_settings: Callable[[ExportSettings], None] = lambda _settings: None,
        confirm: Callable[[], bool] = lambda: True,
    ) -> None:
        super().__init__(dialog_parent)
        self._parent = dialog_parent
        self._document = document
        self._date = date
        self._on_exported = on_exported
        self._sources = sources
        self._settings = settings
        self._save_settings = save_settings
        self._confirm = confirm
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
        return any(anchor.source != "word" for anchor in self._sources.anchors())

    def create_dialog(self) -> ExportDialog:
        settings = self._settings()
        return ExportDialog(
            settings.last_format,
            ExportOptions(
                superscript=settings.superscript_mode,
                untimed=settings.untimed_mode,
                parts_of_speech=self._sources.pos_selected(),
            ),
            self.has_times(),
            self._sources.pos_tagger() is not None,
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
        if not self._confirm():
            return False
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
            font_family=self._sources.font_family(),
        )
        try:
            export_document = self._highlighted(
                build_export_document(
                    document,
                    self._sources.fields(),
                    anonymize,
                    self._sources.anchors() if exporter.timed else (),
                    self._sources.audio_path(),
                    self._sources.comments() if exporter.key == DOCX else (),
                ),
                exporter,
                options.parts_of_speech,
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

    def _highlighted(
        self,
        document: ExportDocument,
        exporter: Exporter,
        parts: tuple[PartOfSpeech, ...],
    ) -> ExportDocument:
        """Dokument z tłem słów wybranych części mowy (gdy format je zna)."""
        if not parts or OPTION_PARTS_OF_SPEECH not in exporter.options:
            return document
        tagger = self._sources.pos_tagger()
        if tagger is None:
            return document
        return with_highlights(
            document,
            [
                (start, end, paper_color(part))
                for start, end, part in tagger.spans(document.text, parts)
            ],
        )

    def _default_name(self, document: Document, anonymize: bool, suffix: str) -> str:
        base = document.metadata.get(SIGNATURE, "").strip() or tr(
            "export.default_name",
            date=self._date().toString("yyyy-MM-dd"),
        )
        anonymized = tr("export.anonymized_suffix") if anonymize else ""
        return f"{base}{anonymized}{suffix}"
