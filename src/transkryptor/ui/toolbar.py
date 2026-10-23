"""Pasek narzędzi okna głównego: notacja, ASR, aktualizacje, ustawienia, sesja.

Sekcja sesji: nowy dokument, projekt (otwórz z listą ostatnich i importem
DOCX, zapisz / zapisz jako), eksport DOCX (zwykły i anonimizowany), zamknij.

Akcje notacji mają kontekst całej aplikacji i są dodane do okna, więc ich
skróty działają z fokusem w edytorze. Definicje markerów i skrótów pochodzą
z ``ui/markers.py`` i ``ui/shortcuts.py``.

W wąskim oknie pasek chowa przyciski według priorytetu (najpierw rzadko
używane; eksport DOCX zostaje zawsze) do menu „Więcej poleceń” (☰). Menu są
dwa, każde obok swojej grupy: znaczniki notacji trafiają do ☰ tuż za nimi
(przed „Szkic ASR”), a narzędzia i polecenia sesji — do ☰ na końcu paska.
Wszystkie akcje są dodane do okna, więc skróty działają także wtedy, gdy
przycisk jest schowany.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCursor, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from transkryptor.i18n import tr
from transkryptor.ui import icons
from transkryptor.ui.markers import MARKERS, SUPERSCRIPT_SHORTCUT
from transkryptor.ui.shortcuts import (
    CLOSE_SHORTCUT,
    EXPORT_SHORTCUT,
    NEW_SHORTCUT,
    OPEN_PROJECT_SHORTCUT,
    SAVE_PROJECT_AS_SHORTCUT,
    SAVE_PROJECT_SHORTCUT,
    SETTINGS_SHORTCUT,
    set_base_tooltip,
)
from transkryptor.ui.theme import set_props


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
    export_as: Callable[[], None] = lambda: None


@dataclass(frozen=True)
class _Slot:
    """Pozycja paska, którą w wąskim oknie przejmuje menu „Więcej poleceń”.

    ``handles`` to uchwyty w pasku (przycisk, opis, separator); w menu trafia
    ``action`` i jej ``extras`` (polecenia z rozwijanej części przycisku).
    """

    section: str
    action: QAction
    handles: tuple[QAction, ...]
    extras: tuple[QAction | QMenu, ...] = ()

    @property
    def shown(self) -> bool:
        return self.handles[0].isVisible()

    def set_shown(self, shown: bool) -> None:
        for handle in self.handles:
            handle.setVisible(shown)


# Kolejność chowania przy zwężaniu okna: najpierw rzadko klikane, na końcu
# zapis. Markery chowają się od końca paska. Eksport DOCX (przycisk główny)
# i menu „Więcej” zostają zawsze.

# Sekcja paska z własnym menu „Więcej” po lewej stronie (za znacznikami);
# pozostałe sekcje chowają się do menu na końcu paska.
NOTATION_SECTION = "notation"
COLLAPSE_ORDER = (
    "snippets",
    *(f"marker:{marker.key}" for marker in reversed(MARKERS)),
    "superscript",
    "asr",
    "settings",
    "new",
    "close",
    "open",
    "save",
)


class _ToolBar(QToolBar):
    """``QToolBar``, który po zmianie szerokości dopasowuje zestaw przycisków."""

    def __init__(self, title: str, parent: QWidget) -> None:
        super().__init__(title, parent)
        self.on_resize: Callable[[], None] = lambda: None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.on_resize()


class MainToolbar:
    """Pasek narzędzi i jego akcje (dostępne jako atrybuty)."""

    def __init__(
        self,
        window: QMainWindow,
        asr_toggle: QAction,
        handlers: ToolbarHandlers,
    ) -> None:
        toolbar = _ToolBar(tr("toolbar.title"), window)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(icons.ICON_SIZE)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.toggleViewAction().setEnabled(False)
        window.addToolBar(toolbar)
        self.toolbar = toolbar
        self._buttons: dict[QAction, QToolButton] = {}
        self._slots: dict[str, _Slot] = {}

        caption = toolbar.addWidget(_caption(tr("toolbar.notation")))
        self.superscript_action = _action(
            window,
            tr("toolbar.superscript"),
            "superscript",
            SUPERSCRIPT_SHORTCUT,
            tr("toolbar.superscript.tooltip"),
            handlers.superscript,
        )
        self._slots["superscript"] = _Slot(
            NOTATION_SECTION,
            self.superscript_action,
            (caption, self._add(self.superscript_action), toolbar.addSeparator()),
        )

        self.marker_actions: dict[str, QAction] = {}
        for marker in MARKERS:
            icon = "pause_marker" if marker.key == "pause" else None
            action = _action(
                window,
                marker.label,
                icon,
                marker.shortcut,
                tr("toolbar.insert", marker=marker.inserted_text.strip()),
                partial(handlers.marker, marker.key),
            )
            # Bez jawnego iconText Qt wycina „...”/„…” z napisu przycisku,
            # przez co „Dopisek [...]” wyświetlał się jako „Dopisek []”.
            action.setIconText(marker.label)
            self._slots[f"marker:{marker.key}"] = _Slot(
                NOTATION_SECTION, action, (self._add(action),)
            )
            self.marker_actions[marker.key] = action

        # Wstawki użytkownika (propozycja 21): menu wypełnia ``SnippetController``.
        # Przycisk od razu rozwija menu; schowana akcja w „Więcej” otwiera je
        # przy kursorze.
        self.snippets_menu = QMenu(tr("toolbar.snippets"), window)
        self.snippets_action = QAction(tr("toolbar.snippets"), window)
        self.snippets_action.setToolTip(tr("toolbar.snippets.tooltip"))
        self.snippets_action.triggered.connect(
            lambda _checked=False: self.snippets_menu.popup(QCursor.pos())
        )
        snippets_handle = self._add(self.snippets_action, menu=self.snippets_menu)
        self._buttons[self.snippets_action].setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self._slots["snippets"] = _Slot(
            NOTATION_SECTION, self.snippets_action, (snippets_handle,)
        )

        # Menu schowanych znaczników stoi tuż za nimi — przed „Szkic ASR”.
        self.notation_more_menu, self.notation_more_button = _more_menu(window)
        self.notation_more_menu.aboutToShow.connect(
            lambda: self._fill_more_menu(self.notation_more_menu, notation=True)
        )
        self._notation_more_handle = toolbar.addWidget(self.notation_more_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # Zamknięty panel ASR wraca tym przełącznikiem.
        self.asr_panel_action = asr_toggle
        asr_toggle.setText(tr("main.asr_dock"))
        icons.set_icon(asr_toggle, "sparkles", "text", "text_muted")
        asr_toggle.setToolTip(tr("toolbar.asr.tooltip"))
        self._slots["asr"] = _Slot("tools", asr_toggle, (self._add(asr_toggle),))

        self.settings_action = _action(
            window,
            tr("toolbar.settings"),
            "settings",
            SETTINGS_SHORTCUT,
            tr("toolbar.settings.tooltip"),
            handlers.settings,
        )
        self._slots["settings"] = _Slot(
            "tools",
            self.settings_action,
            (
                self._add(self.settings_action, icon_only=True),
                toolbar.addSeparator(),
            ),
        )

        self.new_action = QAction(tr("toolbar.new"), window)
        icons.set_icon(self.new_action, "new", "text", "text_muted")
        self.new_action.setShortcut(QKeySequence(NEW_SHORTCUT))
        set_base_tooltip(self.new_action, tr("toolbar.new.tooltip"))
        self.new_action.triggered.connect(
            lambda _checked=False: handlers.new_document()
        )
        self._slots["new"] = _Slot(
            "session", self.new_action, (self._add(self.new_action, icon_only=True),)
        )

        self._recent_provider = handlers.recent_projects
        self._open_recent = handlers.open_recent
        self.open_action = _window_action(
            window,
            tr("toolbar.open"),
            "open",
            OPEN_PROJECT_SHORTCUT,
            tr("toolbar.open.tooltip"),
            handlers.open_project,
        )
        self.import_docx_action = QAction(tr("toolbar.import_docx"), window)
        self.import_docx_action.setToolTip(tr("toolbar.import_docx.tooltip"))
        self.import_docx_action.triggered.connect(
            lambda _checked=False: handlers.import_docx()
        )
        self.clear_recent_action = QAction(tr("toolbar.clear_recent"), window)
        self.clear_recent_action.triggered.connect(
            lambda _checked=False: handlers.clear_recent()
        )
        # Tytuł menu widać, gdy jest podmenu „Więcej poleceń”.
        self.open_menu = QMenu(tr("toolbar.recent"), window)
        self.open_menu.aboutToShow.connect(self.refresh_recent_menu)
        self._slots["open"] = _Slot(
            "session",
            self.open_action,
            (self._add(self.open_action, icon_only=True, menu=self.open_menu),),
            (self.open_menu,),
        )
        self.refresh_recent_menu()

        self.save_action = _window_action(
            window,
            tr("toolbar.save"),
            "save",
            SAVE_PROJECT_SHORTCUT,
            tr("toolbar.save.tooltip"),
            handlers.save_project,
        )
        self.save_as_action = _window_action(
            window,
            tr("toolbar.save_as"),
            None,
            SAVE_PROJECT_AS_SHORTCUT,
            tr("toolbar.save_as.tooltip"),
            handlers.save_project_as,
        )
        save_menu = QMenu(window)
        save_menu.addAction(self.save_as_action)
        self._slots["save"] = _Slot(
            "session",
            self.save_action,
            (self._add(self.save_action, icon_only=True, menu=save_menu),),
            (self.save_as_action,),
        )

        self.export_action = QAction(tr("toolbar.export"), window)
        icons.set_icon(self.export_action, "export", "on_accent", "text_muted")
        self.export_action.setShortcut(QKeySequence(EXPORT_SHORTCUT))
        set_base_tooltip(self.export_action, tr("toolbar.export.tooltip"))
        self.export_action.triggered.connect(lambda _checked=False: handlers.export())
        self.export_anonymized_action = QAction(tr("toolbar.export_anonymized"), window)
        self.export_anonymized_action.setToolTip(
            tr("toolbar.export_anonymized.tooltip")
        )
        self.export_anonymized_action.triggered.connect(
            lambda _checked=False: handlers.export_anonymized()
        )
        self.export_as_action = QAction(tr("toolbar.export_as"), window)
        self.export_as_action.setToolTip(tr("toolbar.export_as.tooltip"))
        self.export_as_action.triggered.connect(
            lambda _checked=False: handlers.export_as()
        )
        export_menu = QMenu(window)
        export_menu.addAction(self.export_anonymized_action)
        export_menu.addSeparator()
        export_menu.addAction(self.export_as_action)
        self._add(self.export_action, menu=export_menu)
        set_props(self._buttons[self.export_action], variant="primary")

        self.close_action = QAction(tr("toolbar.close"), window)
        icons.set_icon(self.close_action, "close", "text_muted", "text_muted")
        self.close_action.setShortcut(QKeySequence(CLOSE_SHORTCUT))
        set_base_tooltip(self.close_action, tr("toolbar.close.tooltip"))
        self.close_action.triggered.connect(lambda _checked=False: handlers.close())
        self._slots["close"] = _Slot(
            "session",
            self.close_action,
            (self._add(self.close_action, icon_only=True),),
        )

        # Skrót akcji działa tylko, gdy akcja należy do widocznego widżetu —
        # samo okno, bo przycisk w pasku może być schowany.
        for action in self._buttons:
            window.addAction(action)

        self.more_menu, self.more_button = _more_menu(window)
        self.more_menu.aboutToShow.connect(
            lambda: self._fill_more_menu(self.more_menu, notation=False)
        )
        self._more_handle = toolbar.addWidget(self.more_button)

        toolbar.on_resize = self.fit_to_width
        self.fit_to_width()

    def button_for(self, action: QAction) -> QToolButton:
        """Przycisk paska wywołujący ``action``."""
        return self._buttons[action]

    def collapsed_actions(self) -> list[QAction]:
        """Akcje, których przyciski są teraz schowane w menu „Więcej poleceń”."""
        return [slot.action for slot in self._slots.values() if not slot.shown]

    def fit_to_width(self) -> None:
        """Chowa do menu „Więcej poleceń” przyciski, które się nie mieszczą.

        Własne dopasowanie zamiast rozszerzenia ``QToolBar``: Qt chowa zawsze
        końcowe przyciski (czyli zapis i eksport), a jego wąski przycisk »
        ginie w stylu motywu.
        """
        toolbar = self.toolbar
        for slot in self._slots.values():
            slot.set_shown(True)
        self._notation_more_handle.setVisible(False)
        self._more_handle.setVisible(False)
        for key in COLLAPSE_ORDER:
            if toolbar.sizeHint().width() <= toolbar.width():
                return
            slot = self._slots[key]
            slot.set_shown(False)
            if slot.section == NOTATION_SECTION:
                self._notation_more_handle.setVisible(True)
            else:
                self._more_handle.setVisible(True)

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
            placeholder = menu.addAction(tr("toolbar.recent.empty"))
            placeholder.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.import_docx_action)
        menu.addAction(self.clear_recent_action)
        self.clear_recent_action.setEnabled(bool(recent))

    def _fill_more_menu(self, menu: QMenu, *, notation: bool) -> None:
        """Schowane pozycje grupy w kolejności paska, sekcje oddzielone kreską."""
        menu.clear()
        section = None
        for slot in self._slots.values():
            if slot.shown or (slot.section == NOTATION_SECTION) != notation:
                continue
            if section is not None and slot.section != section:
                menu.addSeparator()
            section = slot.section
            menu.addAction(slot.action)
            for extra in slot.extras:
                if isinstance(extra, QMenu):
                    menu.addMenu(extra)
                else:
                    menu.addAction(extra)

    def _add(
        self, action: QAction, *, icon_only: bool = False, menu: QMenu | None = None
    ) -> QAction:
        """Dodaje przycisk akcji; zwraca uchwyt, którym można go schować.

        Przycisk powstaje ręcznie, a nie przez ``addAction``: wtedy uchwytem
        byłaby sama akcja, a jej schowanie wyłączyłoby skrót i wpis w menu.
        """
        button = QToolButton()
        button.setDefaultAction(action)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setIconSize(self.toolbar.iconSize())
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if icon_only
            else self.toolbar.toolButtonStyle()
        )
        if menu is not None:
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._buttons[action] = button
        return self.toolbar.addWidget(button)


def _window_action(
    window: QMainWindow,
    label: str,
    icon: str | None,
    shortcut: str,
    tooltip: str,
    handler: Callable[[], object],
) -> QAction:
    """Akcja okna; skrót działa także dla akcji schowanej w menu przycisku."""
    action = QAction(label, window)
    if icon is not None:
        icons.set_icon(action, icon, "text", "text_muted")
    action.setShortcut(QKeySequence(shortcut))
    set_base_tooltip(action, tooltip)
    action.triggered.connect(lambda _checked=False: handler())
    window.addAction(action)
    return action


def _action(
    window: QMainWindow,
    label: str,
    icon: str | None,
    shortcut: str,
    tooltip: str,
    handler: Callable[[], object],
) -> QAction:
    """Akcja ze skrótem działającym z fokusem w edytorze."""
    action = QAction(label, window)
    if icon is not None:
        icons.set_icon(action, icon, "text", "text_muted")
    action.setShortcut(QKeySequence(shortcut))
    action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    set_base_tooltip(action, tooltip)
    action.triggered.connect(lambda _checked=False: handler())
    window.addAction(action)
    return action


def _more_menu(window: QMainWindow) -> tuple[QMenu, QToolButton]:
    """Przycisk ☰ z menu „Więcej poleceń” (wypełnianym przy otwarciu)."""
    menu = QMenu(window)
    button = QToolButton()
    button.setObjectName("more_button")
    icons.set_icon(button, "menu", "text", "text_muted")
    button.setIconSize(icons.ICON_SIZE)
    button.setToolTip(tr("toolbar.more"))
    button.setAccessibleName(tr("toolbar.more"))
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return menu, button


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    set_props(label, role="caption")
    return label
