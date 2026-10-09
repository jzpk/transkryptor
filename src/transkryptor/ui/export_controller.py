"""Eksport transkrypcji do DOCX (REQ-07, REQ-08), także z anonimizacją."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDateEdit, QFileDialog, QWidget

from transkryptor.document.metadata import SIGNATURE, MetadataField
from transkryptor.document.model import Document
from transkryptor.errors import AppError
from transkryptor.export.docx_export import export_docx
from transkryptor.ui.messages import show_error

ANONYMIZED_SUFFIX = "-anonim"


class ExportController(QObject):
    """Wybór pliku, zapis DOCX i oznaczenie dokumentu jako wyeksportowanego."""

    def __init__(
        self,
        dialog_parent: QWidget,
        document: Callable[[], Document],
        date_edit: QDateEdit,
        fields: Callable[[], tuple[MetadataField, ...]],
        on_exported: Callable[[], None],
    ) -> None:
        super().__init__(dialog_parent)
        self._parent = dialog_parent
        self._document = document
        self._date_edit = date_edit
        self._on_exported = on_exported
        self._fields = fields

    def export(self, anonymize: bool = False) -> None:
        """ACC-32: ``anonymize`` pomija pola metryczki oznaczone jako osobowe."""
        document = self._document()
        path, _selected_filter = QFileDialog.getSaveFileName(
            self._parent,
            "Eksport do DOCX (anonimizowany)" if anonymize else "Eksport do DOCX",
            self._default_name(document, anonymize),
            "Dokumenty DOCX (*.docx)",
        )
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        try:
            export_docx(document, Path(path), self._fields(), anonymize=anonymize)
        except AppError as error:
            show_error(self._parent, "Eksport DOCX", error)
            return
        document.mark_exported()
        self._on_exported()

    def _default_name(self, document: Document, anonymize: bool) -> str:
        base = document.metadata.get(SIGNATURE, "").strip() or (
            f"transkrypcja-{self._date_edit.date().toString('yyyy-MM-dd')}"
        )
        return f"{base}{ANONYMIZED_SUFFIX if anonymize else ''}.docx"
