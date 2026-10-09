"""Okna wyboru pliku do zapisu (projekt, DOCX)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from transkryptor.i18n import tr


def ask_save_path(
    parent: QWidget, title: str, default: str, file_filter: str, suffix: str
) -> Path | None:
    """Pyta o ścieżkę zapisu z rozszerzeniem ``suffix``; None = anulowano.

    Okno dialogowe pyta o nadpisanie tylko pliku o wpisanej nazwie. Gdy
    rozszerzenie dopisujemy sami (``AdK_1954`` → ``AdK_1954.transkr``),
    a taki plik istnieje, pytamy o nadpisanie osobno — inaczej zapis
    nadpisałby go bez ostrzeżenia.
    """
    path, _selected_filter = QFileDialog.getSaveFileName(
        parent, title, default, file_filter
    )
    if not path:
        return None
    if path.lower().endswith(suffix):
        return Path(path)
    target = Path(path + suffix)
    if target.exists():
        answer = QMessageBox.question(
            parent,
            tr("file.overwrite.title"),
            tr("file.overwrite.text", name=target.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
    return target
