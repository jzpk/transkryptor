"""Zakładka „Profile” w ustawieniach: profile notacji i wybór aktywnego.

Operacje na liście (nowy, zmiana nazwy, usunięcie, import, eksport) działają
od razu na bibliotece profili; wybrany profil staje się aktywny po „OK”
(zmiany na pozostałych zakładkach trafiają wcześniej do bieżącego profilu).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.errors import AppError
from transkryptor.i18n import tr
from transkryptor.profiles import PROFILE_SUFFIX
from transkryptor.settings import Settings
from transkryptor.ui.messages import show_error
from transkryptor.ui.theme import set_props


class ProfileActions(Protocol):
    """Operacje na bibliotece profili (``ProfileController``)."""

    def names(self) -> list[str]: ...

    def create(self, name: str, copy_current: bool) -> str: ...

    def rename(self, old: str, new: str) -> str | None: ...

    def delete(self, name: str) -> bool: ...

    def import_file(self, path: Path) -> str: ...

    def export_file(self, name: str, path: Path) -> None: ...


def profile_filter() -> str:
    return tr("profiles.file_filter", pattern=f"*{PROFILE_SUFFIX}")


class ProfilesPage(QWidget):
    """Lista profili z przyciskami; zaznaczony profil to profil aktywny."""

    def __init__(self, actions: ProfileActions | None = None) -> None:
        super().__init__()
        self._actions = actions
        self._active = ""
        self._build_widgets()
        self._build_layout()
        self._connect_signals()

    def _build_widgets(self) -> None:
        self.hint = QLabel(tr("settings.profiles.hint"))
        self.hint.setWordWrap(True)
        set_props(self.hint, role="muted")
        self.profiles_list = QListWidget()
        self.profiles_list.setObjectName("profiles_list")
        self.profiles_list.setAccessibleName(tr("settings.tab.profiles"))
        self.profiles_list.setAccessibleDescription(tr("settings.profiles.hint"))
        self.new_button = QPushButton(tr("settings.profiles.new"))
        self.copy_button = QPushButton(tr("settings.profiles.copy"))
        self.rename_button = QPushButton(tr("settings.profiles.rename"))
        self.delete_button = QPushButton(tr("settings.profiles.delete"))
        self.delete_button.setToolTip(tr("settings.profiles.delete.tooltip"))
        self.import_button = QPushButton(tr("settings.profiles.import"))
        self.export_button = QPushButton(tr("settings.profiles.export"))
        for button in self._buttons():
            button.setEnabled(self._actions is not None)

    def _buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.new_button,
            self.copy_button,
            self.rename_button,
            self.delete_button,
            self.import_button,
            self.export_button,
        )

    def _build_layout(self) -> None:
        edit_row = QHBoxLayout()
        for button in self._buttons()[:4]:
            edit_row.addWidget(button)
        edit_row.addStretch(1)
        file_row = QHBoxLayout()
        for button in self._buttons()[4:]:
            file_row.addWidget(button)
        file_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.hint)
        layout.addWidget(self.profiles_list, stretch=1)
        layout.addLayout(edit_row)
        layout.addLayout(file_row)

    def _connect_signals(self) -> None:
        self.new_button.clicked.connect(lambda: self._on_new(copy_current=False))
        self.copy_button.clicked.connect(lambda: self._on_new(copy_current=True))
        self.rename_button.clicked.connect(self._on_rename)
        self.delete_button.clicked.connect(self._on_delete)
        self.import_button.clicked.connect(self._on_import)
        self.export_button.clicked.connect(self._on_export)
        self.profiles_list.currentItemChanged.connect(
            lambda *_args: self._update_buttons()
        )

    # --- protokół strony ustawień ----------------------------------------

    def load(self, settings: Settings) -> None:
        self._active = settings.profiles.active
        self._fill(self._active)

    def apply(self, settings: Settings) -> Settings:
        selected = self.selected() or self._active
        return replace(settings, profiles=replace(settings.profiles, active=selected))

    # --- lista -----------------------------------------------------------

    def selected(self) -> str:
        item = self.profiles_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def names(self) -> list[str]:
        return [
            str(self.profiles_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.profiles_list.count())
        ]

    def select(self, name: str) -> None:
        for row in range(self.profiles_list.count()):
            if self.profiles_list.item(row).data(Qt.ItemDataRole.UserRole) == name:
                self.profiles_list.setCurrentRow(row)
                return

    def _fill(self, selected: str) -> None:
        self.profiles_list.clear()
        names = self._actions.names() if self._actions is not None else []
        for name in names:
            text = (
                tr("settings.profiles.active_item", name=name)
                if name == self._active
                else name
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.profiles_list.addItem(item)
        self.select(selected)
        self._update_buttons()

    def _update_buttons(self) -> None:
        if self._actions is None:
            return
        name = self.selected()
        for button in (self.rename_button, self.export_button):
            button.setEnabled(bool(name))
        # Profil, z którym okno pracuje, nie może zniknąć.
        self.delete_button.setEnabled(bool(name) and name != self._active)

    # --- operacje --------------------------------------------------------

    def create_profile(self, name: str, copy_current: bool) -> str | None:
        actions = self._actions
        if actions is None or not name.strip():
            return None
        created = self._run(lambda: actions.create(name, copy_current))
        if created is not None:
            self._fill(created)
        return created

    def rename_profile(self, old: str, new: str) -> str | None:
        actions = self._actions
        if actions is None or not new.strip():
            return None
        renamed = self._run(lambda: actions.rename(old, new))
        if renamed is not None:
            if old == self._active:
                self._active = renamed
            self._fill(renamed)
        return renamed

    def delete_profile(self, name: str) -> bool:
        actions = self._actions
        if actions is None or name == self._active:
            return False
        deleted = bool(self._run(lambda: actions.delete(name)))
        self._fill(self._active)
        return deleted

    def import_profile(self, path: Path) -> str | None:
        actions = self._actions
        if actions is None:
            return None
        imported = self._run(lambda: actions.import_file(path))
        if imported is not None:
            self._fill(imported)
        return imported

    def export_profile(self, name: str, path: Path) -> bool:
        actions = self._actions
        if actions is None:
            return False

        def export() -> bool:
            actions.export_file(name, path)
            return True

        return bool(self._run(export))

    def _run[T](self, operation: Callable[[], T]) -> T | None:
        """Wynik operacji albo None po błędzie pokazanym użytkownikowi."""
        try:
            return operation()
        except AppError as error:
            show_error(self, tr("settings.profiles.error"), error)
            return None

    def _on_new(self, copy_current: bool) -> None:
        name, accepted = QInputDialog.getText(
            self, tr("settings.profiles.new_title"), tr("settings.profiles.name")
        )
        if accepted:
            self.create_profile(name, copy_current)

    def _on_rename(self) -> None:
        old = self.selected()
        if not old:
            return
        name, accepted = QInputDialog.getText(
            self,
            tr("settings.profiles.rename_title"),
            tr("settings.profiles.name"),
            text=old,
        )
        if accepted:
            self.rename_profile(old, name)

    def _on_delete(self) -> None:
        name = self.selected()
        if not name:
            return
        answer = QMessageBox.question(
            self,
            tr("settings.profiles.delete_title"),
            tr("settings.profiles.delete_question", name=name),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_profile(name)

    def _on_import(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, tr("settings.profiles.import_dialog"), "", profile_filter()
        )
        if path:
            self.import_profile(Path(path))

    def _on_export(self) -> None:
        name = self.selected()
        if not name:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            tr("settings.profiles.export_dialog"),
            f"{name}{PROFILE_SUFFIX}",
            profile_filter(),
        )
        if path:
            self.export_profile(name, Path(path))
