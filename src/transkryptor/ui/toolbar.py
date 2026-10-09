"""Pasek narzędzi okna głównego: notacja, ASR, aktualizacje, ustawienia, sesja.

Sekcja sesji: nowy dokument, projekt (otwórz z listą ostatnich i importem
DOCX, zapisz / zapisz jako), eksport DOCX (zwykły i anonimizowany), zamknij.

Akcje notacji mają kontekst całej aplikacji i są dodane do okna, więc ich
skróty działają z fokusem w edytorze. Definicje markerów i skrótów pochodzą
z ``ui/markers.py`` i ``ui/shortcuts.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from transkryptor.ui import icons
from transkryptor.ui.markers import MARKERS, SUPERSCRIPT_SHORTCUT
from transkryptor.ui.shortcuts import SETTINGS_SHORTCUT
from transkryptor.ui.shortcuts import tooltip_with_shortcut as _tooltip
from transkryptor.ui.theme import set_props, tokens


@dataclass(frozen=True)
class ToolbarHandlers:
    superscript: Callable[[], None]
    marker: Callable[[str], None]
    settings: Callable[[], None]
    new_document: Callable[[], None]
    export: Callable[[], None]
    close: Callable[[], object]
    open_project: Callable[[], None]
    open_recent: Callable[[str], object]
    clear_recent: Callable[[], None]
    recent_projects: Callable[[], list[str]]
    save_project: Callable[[], object]
    save_project_as: Callable[[], object]
    import_docx: Callable[[], None]
    export_anonymized: Callable[[], None]


class MainToolbar:
    """Pasek narzędzi i jego akcje (dostępne jako atrybuty)."""

    def __init__(
        self,
        window: QMainWindow,
        asr_toggle: QAction,
        update_action: QAction,
        handlers: ToolbarHandlers,
    ) -> None:
        t = tokens()
        toolbar = QToolBar("Pasek narzędzi", window)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(icons.ICON_SIZE)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.toggleViewAction().setEnabled(False)
        window.addToolBar(toolbar)
        self.toolbar = toolbar

        toolbar.addWidget(_caption("NOTACJA"))
        self.superscript_action = _action(
            window,
            "Indeks górny",
            icons.icon("superscript", t.text, t.text_muted),
            SUPERSCRIPT_SHORTCUT,
            "Indeks górny zaznaczonych liter",
            handlers.superscript,
        )
        toolbar.addAction(self.superscript_action)

        toolbar.addSeparator()
        self.marker_actions: dict[str, QAction] = {}
        for marker in MARKERS:
            icon = (
                icons.icon("pause_marker", t.text, t.text_muted)
                if marker.key == "pause"
                else None
            )
            action = _action(
                window,
                marker.label,
                icon,
                marker.shortcut,
                f"Wstaw {marker.inserted_text.strip()}",
                partial(handlers.marker, marker.key),
            )
            # Bez jawnego iconText Qt wycina „...”/„…” z napisu przycisku,
            # przez co „Dopisek [...]” wyświetlał się jako „Dopisek []”.
            action.setIconText(marker.label)
            toolbar.addAction(action)
            self.marker_actions[marker.key] = action

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # Zamknięty panel ASR wraca tym przełącznikiem.
        self.asr_panel_action = asr_toggle
        asr_toggle.setText("Szkic ASR")
        asr_toggle.setIcon(icons.icon("sparkles", t.text, t.text_muted))
        asr_toggle.setToolTip("Pokaż lub ukryj panel Szkic ASR")
        toolbar.addAction(asr_toggle)

        self.update_action = update_action
        update_action.setIcon(icons.icon("download", t.text, t.text_muted))
        toolbar.addAction(update_action)
        _icon_only(toolbar, update_action)

        self.settings_action = _action(
            window,
            "Ustawienia…",
            icons.icon("settings", t.text, t.text_muted),
            SETTINGS_SHORTCUT,
            "Odtwarzacz, edytor i notacja — preferencje",
            handlers.settings,
        )
        toolbar.addAction(self.settings_action)
        _icon_only(toolbar, self.settings_action)
        toolbar.addSeparator()

        self.new_action = QAction("Nowy dokument", window)
        self.new_action.setIcon(icons.icon("new", t.text, t.text_muted))
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.setToolTip(
            _tooltip("Wyczyść edytor i zacznij od nowa", "Ctrl+N")
        )
        self.new_action.triggered.connect(
            lambda _checked=False: handlers.new_document()
        )
        toolbar.addAction(self.new_action)
        _icon_only(toolbar, self.new_action)

        self._recent_provider = handlers.recent_projects
        self._open_recent = handlers.open_recent
        self.open_action = _window_action(
            window,
            "Otwórz projekt…",
            icons.icon("open", t.text, t.text_muted),
            OPEN_PROJECT_SHORTCUT,
            "Otwórz zapisany projekt (.transkr)",
            handlers.open_project,
        )
        toolbar.addAction(self.open_action)
        _icon_only(toolbar, self.open_action)
        self.import_docx_action = QAction("Importuj DOCX…", window)
        self.import_docx_action.setToolTip(
            "Wczytaj tekst i metryczkę z dokumentu Word jako nowy projekt"
        )
        self.import_docx_action.triggered.connect(
            lambda _checked=False: handlers.import_docx()
        )
        self.clear_recent_action = QAction("Wyczyść listę ostatnich", window)
        self.clear_recent_action.triggered.connect(
            lambda _checked=False: handlers.clear_recent()
        )
        self.open_menu = QMenu(window)
        self.open_menu.aboutToShow.connect(self.refresh_recent_menu)
        _menu_button(toolbar, self.open_action, self.open_menu)
        self.refresh_recent_menu()

        self.save_action = _window_action(
            window,
            "Zapisz projekt",
            icons.icon("save", t.text, t.text_muted),
            SAVE_PROJECT_SHORTCUT,
            "Zapisz tekst, metryczkę, szkic ASR i stan odtwarzacza",
            handlers.save_project,
        )
        toolbar.addAction(self.save_action)
        _icon_only(toolbar, self.save_action)
        self.save_as_action = _window_action(
            window,
            "Zapisz projekt jako…",
            None,
            SAVE_PROJECT_AS_SHORTCUT,
            "Zapisz projekt w nowym pliku",
            handlers.save_project_as,
        )
        save_menu = QMenu(window)
        save_menu.addAction(self.save_as_action)
        _menu_button(toolbar, self.save_action, save_menu)

        self.export_action = QAction("Eksportuj DOCX…", window)
        self.export_action.setIcon(icons.icon("export", t.on_accent, t.text_muted))
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.setToolTip(
            _tooltip("Zapisz transkrypcję jako plik Word", "Ctrl+E")
        )
        self.export_action.triggered.connect(lambda _checked=False: handlers.export())
        toolbar.addAction(self.export_action)
        set_props(toolbar.widgetForAction(self.export_action), variant="primary")
        self.export_anonymized_action = QAction(
            "Eksportuj DOCX z anonimizacją…", window
        )
        self.export_anonymized_action.setToolTip(
            "Eksport bez pól metryczki oznaczonych jako dane osobowe"
        )
        self.export_anonymized_action.triggered.connect(
            lambda _checked=False: handlers.export_anonymized()
        )
        export_menu = QMenu(window)
        export_menu.addAction(self.export_anonymized_action)
        _menu_button(toolbar, self.export_action, export_menu)

        self.close_action = QAction("Zamknij", window)
        self.close_action.setIcon(icons.icon("close", t.text_muted, t.text_muted))
        self.close_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_action.setToolTip(_tooltip("Zamknij aplikację", "Ctrl+W"))
        self.close_action.triggered.connect(lambda _checked=False: handlers.close())
        toolbar.addAction(self.close_action)
        _icon_only(toolbar, self.close_action)

    def refresh_recent_menu(self) -> None:
        """Menu „Otwórz”: ostatnie projekty, import DOCX, czyszczenie listy."""
        menu = self.open_menu
        menu.clear()
        recent = self._recent_provider()
        for path in recent:
            action = menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.setStatusTip(path)
            action.triggered.connect(
                lambda _checked=False, chosen=path: self._open_recent(chosen)
            )
        if not recent:
            placeholder = menu.addAction("Brak ostatnich projektów")
            placeholder.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.import_docx_action)
        menu.addAction(self.clear_recent_action)
        self.clear_recent_action.setEnabled(bool(recent))


OPEN_PROJECT_SHORTCUT = "Ctrl+O"
SAVE_PROJECT_SHORTCUT = "Ctrl+S"
SAVE_PROJECT_AS_SHORTCUT = "Ctrl+Shift+S"


def _window_action(
    window: QMainWindow,
    label: str,
    icon,
    shortcut: str,
    tooltip: str,
    handler: Callable[[], object],
) -> QAction:
    """Akcja okna; skrót działa także dla akcji schowanej w menu przycisku."""
    action = QAction(label, window)
    if icon is not None:
        action.setIcon(icon)
    action.setShortcut(QKeySequence(shortcut))
    action.setToolTip(_tooltip(tooltip, shortcut))
    action.triggered.connect(lambda _checked=False: handler())
    window.addAction(action)
    return action


def _menu_button(toolbar: QToolBar, action: QAction, menu: QMenu) -> None:
    """Przycisk akcji z rozwijanym menu dodatkowych poleceń."""
    button = toolbar.widgetForAction(action)
    if isinstance(button, QToolButton):
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)


def _action(
    window: QMainWindow,
    label: str,
    icon,
    shortcut: str,
    tooltip: str,
    handler: Callable[[], object],
) -> QAction:
    """Akcja ze skrótem działającym z fokusem w edytorze."""
    action = QAction(label, window)
    if icon is not None:
        action.setIcon(icon)
    action.setShortcut(QKeySequence(shortcut))
    action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    action.setToolTip(_tooltip(tooltip, shortcut))
    action.triggered.connect(lambda _checked=False: handler())
    window.addAction(action)
    return action


def _icon_only(toolbar: QToolBar, action: QAction) -> None:
    button = toolbar.widgetForAction(action)
    if isinstance(button, QToolButton):
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    set_props(label, role="caption")
    return label
