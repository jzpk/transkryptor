"""Pasek wyszukiwania i zamiany pod edytorem (propozycja 20).

Widżet zawiera wyłącznie pola i przyciski; logikę (trafienia, podświetlenia,
zamiana) prowadzi ``SearchController``. Esc z fokusem w pasku zamyka go
i oddaje fokus edytorowi.
"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
)

from transkryptor.document.search import ParsedReplacement, SearchOptions
from transkryptor.ui import icons
from transkryptor.ui.shortcuts import FIND_NEXT_SHORTCUT, FIND_PREVIOUS_SHORTCUT
from transkryptor.ui.shortcuts import tooltip_with_shortcut as _tooltip
from transkryptor.ui.theme import set_props, tokens

REPLACE_PLACEHOLDER = "Zamień na… (^n — indeks górny, \\^ — znak ^)"


class SearchBar(QWidget):
    """Pola „Szukaj” / „Zamień na”, opcje, licznik, błąd i podgląd zamiennika."""

    query_changed = Signal()  # tekst lub opcje wyszukiwania
    replacement_changed = Signal()
    next_requested = Signal()
    previous_requested = Signal()
    replace_requested = Signal()
    replace_all_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("search_bar")
        t = tokens()

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Szukaj…")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.addAction(
            icons.icon("search", t.text_muted), QLineEdit.ActionPosition.LeadingPosition
        )
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText(REPLACE_PLACEHOLDER)
        self.replace_edit.setClearButtonEnabled(True)

        self.case_check = QCheckBox("Aa")
        self.case_check.setToolTip("Uwzględniaj wielkość liter")
        self.whole_words_check = QCheckBox("Całe słowa")
        self.regex_check = QCheckBox(".*")
        self.regex_check.setToolTip("Wyrażenie regularne")

        self.count_label = QLabel()
        set_props(self.count_label, role="muted")
        self.error_label = QLabel()
        set_props(self.error_label, role="status", tone="danger")
        self.error_label.hide()
        self.preview_label = QLabel()
        self.preview_label.setTextFormat(Qt.TextFormat.RichText)
        self.preview_label.setToolTip("Podgląd zamiennika z indeksem górnym")
        set_props(self.preview_label, role="muted")

        self.previous_button = QPushButton("Poprzedni")
        self.previous_button.setToolTip(
            _tooltip("Poprzednie trafienie", FIND_PREVIOUS_SHORTCUT)
        )
        self.next_button = QPushButton("Następny")
        self.next_button.setToolTip(_tooltip("Następne trafienie", FIND_NEXT_SHORTCUT))
        self.replace_button = QPushButton("Zamień")
        self.replace_all_button = QPushButton("Zamień wszystkie")
        self.replace_all_button.setToolTip(
            "Zamień wszystkie trafienia (jedno cofnięcie)"
        )
        self.close_button = QToolButton()
        self.close_button.setIcon(icons.icon("close", t.text_muted))
        self.close_button.setToolTip(_tooltip("Zamknij wyszukiwanie", "Esc"))
        self.close_button.setAutoRaise(True)

        layout = QGridLayout(self)
        layout.setContentsMargins(16, 6, 12, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        layout.addWidget(self.find_edit, 0, 0)
        layout.addWidget(self.case_check, 0, 1)
        layout.addWidget(self.whole_words_check, 0, 2)
        layout.addWidget(self.regex_check, 0, 3)
        layout.addWidget(self.count_label, 0, 4)
        layout.addWidget(self.previous_button, 0, 5)
        layout.addWidget(self.next_button, 0, 6)
        layout.addWidget(self.close_button, 0, 7)
        layout.addWidget(self.replace_edit, 1, 0)
        layout.addWidget(self.preview_label, 1, 1, 1, 4)
        layout.addWidget(self.replace_button, 1, 5)
        layout.addWidget(self.replace_all_button, 1, 6)
        layout.addWidget(self.error_label, 2, 0, 1, 8)
        layout.setColumnStretch(0, 1)
        self._replace_row = (
            self.replace_edit,
            self.preview_label,
            self.replace_button,
            self.replace_all_button,
        )

        close_action = QAction(self)
        close_action.setShortcut(QKeySequence("Esc"))
        close_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        close_action.triggered.connect(self.close_requested)
        self.addAction(close_action)

        self.find_edit.textChanged.connect(self.query_changed)
        for check in (self.case_check, self.whole_words_check, self.regex_check):
            check.toggled.connect(self.query_changed)
        self.replace_edit.textChanged.connect(self.replacement_changed)
        self.find_edit.returnPressed.connect(self.next_requested)
        self.replace_edit.returnPressed.connect(self.replace_requested)
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button.clicked.connect(self.next_requested)
        self.replace_button.clicked.connect(self.replace_requested)
        self.replace_all_button.clicked.connect(self.replace_all_requested)
        self.close_button.clicked.connect(self.close_requested)

        self.set_replace_mode(False)
        self.hide()

    def options(self) -> SearchOptions:
        return SearchOptions(
            case_sensitive=self.case_check.isChecked(),
            whole_words=self.whole_words_check.isChecked(),
            regex=self.regex_check.isChecked(),
        )

    def set_replace_mode(self, enabled: bool) -> None:
        for widget in self._replace_row:
            widget.setVisible(enabled)

    def is_replace_mode(self) -> bool:
        return self.replace_edit.isVisibleTo(self)

    def set_count(self, current: int | None, total: int) -> None:
        """Licznik „3 z 12” (``current`` od 0) albo „Brak wyników”."""
        if not self.find_edit.text():
            self.count_label.setText("")
        elif total == 0:
            self.count_label.setText("Brak wyników")
        elif current is None:
            self.count_label.setText(f"{total} wyn.")
        else:
            self.count_label.setText(f"{current + 1} z {total}")
        has_matches = total > 0
        for button in (
            self.previous_button,
            self.next_button,
            self.replace_button,
            self.replace_all_button,
        ):
            button.setEnabled(has_matches)

    def set_error(self, message: str | None) -> None:
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))

    def set_preview(self, replacement: ParsedReplacement | None) -> None:
        """Podgląd zamiennika z indeksem górnym (``<sup>``)."""
        if replacement is None or not replacement.text:
            self.preview_label.setText("")
            return
        parts: list[str] = []
        last = 0
        text = replacement.text
        for start, end in replacement.superscript_ranges:
            parts.append(escape(text[last:start]))
            parts.append(f"<sup>{escape(text[start:end])}</sup>")
            last = end
        parts.append(escape(text[last:]))
        self.preview_label.setText("→ " + "".join(parts))
