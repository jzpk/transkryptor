"""Zapis tabeli okna (statystyki, pola tematyczne) do CSV albo XLSX.

Teksty okna zapisu biorą się z kluczy ``<prefix>.export.dialog``,
``<prefix>.export.filter`` (z polem ``{pattern}``) i ``<prefix>.export.error``,
a nazwa arkusza XLSX - z ``<prefix>.title``.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QWidget

from transkryptor.corpus.catalog import Table, save_table
from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.ui.messages import show_error


def export_table(
    parent: QWidget, table: Table, default_name: str, suffix: str, prefix: str
) -> bool:
    """Pyta o plik i zapisuje tabelę; False - anulowano albo błąd."""
    path, _selected = QFileDialog.getSaveFileName(
        parent,
        tr(f"{prefix}.export.dialog"),
        f"{default_name}{suffix}",
        tr(f"{prefix}.export.filter", pattern=f"*{suffix}"),
    )
    if not path:
        return False
    if not path.lower().endswith(suffix):
        path += suffix
    try:
        save_table(table, path, tr(f"{prefix}.title"))
    except AppError as error:
        show_error(parent, tr(f"{prefix}.export.error"), error)
        return False
    return True
