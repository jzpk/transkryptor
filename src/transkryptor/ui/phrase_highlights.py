"""Trwałe podświetlanie fraz w tekście, jak zakreślacz (zgłoszenie #36).

Frazę dodaje przycisk „Podświetl” paska wyszukiwania - z opcjami
wyszukiwania (wielkość liter, całe słowa, wyrażenie regularne). Przycisk jest
przełącznikiem: dla frazy już podświetlonej jest wciśnięty i usuwa
podświetlenie (``bind_search_bar``). Każda fraza
ma własny kolor, a jej wystąpienia zostają podświetlone także po zamknięciu
paska i są przeliczane po każdej zmianie tekstu. Podświetlenia należą do
widoku (warstwa ``PHRASE_LAYER``): nie trafiają do projektu ani eksportu.
Listę fraz i ich usuwanie pokazuje menu „Podświetlenia” na pasku narzędzi.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QMenu

from transkryptor.document.search import (
    SearchError,
    SearchOptions,
    compile_query,
    find_all,
)
from transkryptor.i18n import tr, tr_plural
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import PHRASE_LAYER
from transkryptor.ui.search_bar import SearchBar
from transkryptor.ui.span_layer import SpanLayer

# Kolory kolejnych fraz (jak zakreślacze); po wyczerpaniu - od początku.
PHRASE_COLORS = ("#f2c200", "#3cbf6a", "#4a9df8", "#f062a8", "#ff8a2a", "#9b6bff")
PHRASE_ALPHA = 110
REFRESH_DEBOUNCE_MS = 200
SWATCH_PX = 12


@dataclass(frozen=True)
class Phrase:
    query: str
    options: SearchOptions
    color: str

    def qcolor(self) -> QColor:
        color = QColor(self.color)
        color.setAlpha(PHRASE_ALPHA)
        return color


class PhraseHighlighter(QObject):
    """Frazy podświetlane na stałe i ich wystąpienia w tekście edytora."""

    changed = Signal()  # dodanie lub usunięcie frazy

    def __init__(
        self,
        editor: TranscriptionEditor,
        open_find: Callable[[], None],
        show_status: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._open_find = open_find
        self._show_status = show_status
        self._phrases: list[Phrase] = []
        self._matches: dict[Phrase, list[tuple[int, int]]] = {}
        self._layer = SpanLayer(editor, PHRASE_LAYER, self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        editor.document().contentsChanged.connect(self._on_text_changed)

    @property
    def phrases(self) -> tuple[Phrase, ...]:
        return tuple(self._phrases)

    def count(self, phrase: Phrase) -> int:
        """Liczba wystąpień frazy w bieżącym tekście."""
        return len(self._matches.get(phrase, ()))

    def find(self, query: str, options: SearchOptions) -> Phrase | None:
        """Podświetlona fraza o tym tekście i opcjach wyszukiwania."""
        return next(
            (p for p in self._phrases if p.query == query and p.options == options),
            None,
        )

    def toggle(self, query: str, options: SearchOptions) -> None:
        """Przycisk „Podświetl”: dodaje frazę albo usuwa już podświetloną."""
        phrase = self.find(query, options)
        if phrase is None:
            self.add(query, options)
            return
        self.remove(phrase)
        self._show_status(tr("highlights.phrase.removed", phrase=query))

    def add(self, query: str, options: SearchOptions) -> Phrase | None:
        """Dodaje frazę z opcjami wyszukiwania; None - pusta, błędna lub już jest."""
        if not query:
            return None
        if self.find(query, options) is not None:
            self._show_status(tr("highlights.phrase.exists", phrase=query))
            return None
        try:
            compile_query(query, options)
        except SearchError as error:
            self._show_status(str(error))
            return None
        used = {phrase.color for phrase in self._phrases}
        free = [color for color in PHRASE_COLORS if color not in used]
        color = (free or PHRASE_COLORS)[0]
        phrase = Phrase(query, options, color)
        self._phrases.append(phrase)
        self.refresh()
        self.changed.emit()
        self._show_status(
            tr_plural("highlights.phrase.added", self.count(phrase), phrase=query)
        )
        return phrase

    def remove(self, phrase: Phrase) -> None:
        if phrase in self._phrases:
            self._phrases.remove(phrase)
            self.refresh()
            self.changed.emit()

    def clear(self) -> None:
        self._phrases.clear()
        self.refresh()
        self.changed.emit()

    def _on_text_changed(self) -> None:
        if self._phrases:
            self._timer.start()

    def refresh(self) -> None:
        """Przelicza wystąpienia wszystkich fraz i odświeża podświetlenia."""
        self._timer.stop()
        text = self._editor.plain_text()
        self._matches = {}
        spans: list[tuple[int, int, QColor]] = []
        for phrase in self._phrases:
            try:
                matches = find_all(text, compile_query(phrase.query, phrase.options))
            except SearchError:  # SEC-03: wzorzec zbyt kosztowny
                matches = []
            self._matches[phrase] = matches
            color = phrase.qcolor()
            spans.extend((start, end, color) for start, end in matches)
        self._layer.set_spans(spans)

    # --- menu „Podświetlenia” ----------------------------------------------

    def fill_menu(self, menu: QMenu) -> None:
        """Polecenie dodania frazy, lista fraz (odznaczenie usuwa) i czyszczenie."""
        menu.addSection(tr("highlights.phrase.title"))
        add = menu.addAction(tr("highlights.phrase.add"))
        add.setToolTip(tr("highlights.phrase.add.tooltip"))
        add.triggered.connect(lambda _checked=False: self._open_find())
        if not self._phrases:
            empty = menu.addAction(tr("highlights.phrase.none"))
            empty.setEnabled(False)
            return
        for phrase in self._phrases:
            action = menu.addAction(
                swatch(phrase.qcolor()),
                tr(
                    "highlights.phrase.item",
                    phrase=phrase.query,
                    count=self.count(phrase),
                ),
            )
            action.setCheckable(True)
            action.setChecked(True)
            action.setToolTip(tr("highlights.phrase.item.tooltip"))
            action.toggled.connect(lambda _checked, chosen=phrase: self.remove(chosen))
        clear = menu.addAction(tr("highlights.phrase.clear"))
        clear.triggered.connect(lambda _checked=False: self.clear())


def bind_search_bar(bar: SearchBar, highlighter: PhraseHighlighter) -> None:
    """Przycisk „Podświetl” przełącza frazę i pokazuje, czy jest podświetlona."""

    def show_state() -> None:
        phrase = highlighter.find(bar.find_edit.text(), bar.options())
        bar.set_highlighted(phrase is not None)

    bar.highlight_requested.connect(highlighter.toggle)
    bar.query_changed.connect(show_state)
    highlighter.changed.connect(show_state)


def swatch(color: QColor) -> QIcon:
    """Kwadracik koloru podświetlenia do pozycji menu."""
    pixmap = QPixmap(SWATCH_PX, SWATCH_PX)
    opaque = QColor(color)
    opaque.setAlpha(255)
    pixmap.fill(opaque)
    return QIcon(pixmap)
