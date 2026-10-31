"""Zakładka „Samouczki” okna ustawień: lista przewodników i start przy uruchomieniu.

Wybrany samouczek ogłasza sygnał ``tutorial_requested`` - okno ustawień
zamyka się wtedy jak po „OK”, a samouczek uruchamia okno główne.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.settings import Settings
from transkryptor.ui.tutorial_content import TUTORIALS


class TutorialsPage(QWidget):
    """Strona ustawień z listą samouczków (protokół ``SettingsPage``)."""

    tutorial_requested = Signal(str)  # klucz samouczka

    def __init__(self) -> None:
        super().__init__()
        intro = QLabel(tr("settings.tutorials.intro"))
        intro.setWordWrap(True)
        self.list = QListWidget()
        self.list.setObjectName("tutorials_list")
        self.list.setWordWrap(True)
        for tutorial in TUTORIALS:
            item = QListWidgetItem(f"{tutorial.title}\n{tutorial.summary}")
            item.setData(Qt.ItemDataRole.UserRole, tutorial.key)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.start_button = QPushButton(tr("settings.tutorials.start"))
        self.show_on_start_check = QCheckBox(tr("settings.tutorials.show_on_start"))
        self.show_on_start_check.setToolTip(
            tr("settings.tutorials.show_on_start.tooltip")
        )
        self.start_button.clicked.connect(self._request_current)
        self.list.itemActivated.connect(lambda _item: self._request_current())
        self._build_layout(intro)

    def _build_layout(self, intro: QLabel) -> None:
        buttons = QHBoxLayout()
        buttons.addWidget(self.show_on_start_check, stretch=1)
        buttons.addWidget(self.start_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addWidget(self.list, stretch=1)
        layout.addLayout(buttons)

    def select(self, key: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.list.setCurrentRow(row)
                return

    def _request_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.tutorial_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def load(self, settings: Settings) -> None:
        self.show_on_start_check.setChecked(settings.tutorial.show_on_start)

    def apply(self, settings: Settings) -> Settings:
        return replace(
            settings,
            tutorial=replace(
                settings.tutorial,
                show_on_start=self.show_on_start_check.isChecked(),
            ),
        )
