"""Eksport transkrypcji do DOCX (REQ-07, REQ-08)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDateEdit, QFileDialog, QWidget

from transkryptor.document.model import Document
from transkryptor.errors import AppError
from transkryptor.export.docx_export import export_docx
from transkryptor.ui.messages import show_error


class ExportController(QObject):
    """Wybór pliku, zapis DOCX i oznaczenie dokumentu jako wyeksportowanego."""

    def __init__(
        self,
        dialog_parent: QWidget,
        document: Callable[[], Document],
        date_edit: QDateEdit,
        on_exported: Callable[[], None],
    ) -> None:
        super().__init__(dialog_parent)
        self._parent = dialog_parent
        self._document = document
        self._date_edit = date_edit
        self._on_exported = on_exported

    def export(self) -> None:
        default_name = (
            f"transkrypcja-{self._date_edit.date().toString('yyyy-MM-dd')}.docx"
        )
        path, _selected_filter = QFileDialog.getSaveFileName(
            self._parent, "Eksport do DOCX", default_name, "Dokumenty DOCX (*.docx)"
        )
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        document = self._document()
        try:
            export_docx(document, Path(path))
        except AppError as error:
            show_error(self._parent, "Eksport DOCX", error)
            return
        document.mark_exported()
        self._on_exported()
