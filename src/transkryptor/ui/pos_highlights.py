"""Podświetlanie słów według części mowy (zgłoszenie #35).

W menu „Podświetlenia” na pasku narzędzi można zaznaczyć jedną albo kilka
części mowy (rzeczowniki, czasowniki, przymiotniki…); każda ma własny kolor.
Części mowy podaje Morfeusz 2 (``document/parts_of_speech.py``), wczytywany
dopiero przy pierwszym zaznaczeniu. Podświetlenia należą do widoku (warstwa
``POS_LAYER``): nie trafiają do projektu ani eksportu.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu

from transkryptor.document.parts_of_speech import (
    AnalyserUnavailable,
    PartOfSpeech,
    PartOfSpeechTagger,
    morfeusz_analyser,
)
from transkryptor.i18n import tr
from transkryptor.ui.editor import TranscriptionEditor
from transkryptor.ui.highlights import POS_LAYER
from transkryptor.ui.phrase_highlights import swatch
from transkryptor.ui.span_layer import SpanLayer

POS_COLORS: dict[PartOfSpeech, str] = {
    PartOfSpeech.NOUN: "#4a9df8",
    PartOfSpeech.VERB: "#f0506e",
    PartOfSpeech.ADJECTIVE: "#3cbf6a",
    PartOfSpeech.ADVERB: "#ff8a2a",
    PartOfSpeech.PRONOUN: "#9b6bff",
    PartOfSpeech.NUMERAL: "#14b8b0",
    PartOfSpeech.PREPOSITION: "#a0785a",
    PartOfSpeech.CONJUNCTION: "#8a94a6",
    PartOfSpeech.PARTICLE: "#e0b400",
    PartOfSpeech.INTERJECTION: "#e05cd0",
}
POS_ALPHA = 90
REFRESH_DEBOUNCE_MS = 300


def pos_color(part: PartOfSpeech) -> QColor:
    color = QColor(POS_COLORS[part])
    color.setAlpha(POS_ALPHA)
    return color


def default_tagger() -> PartOfSpeechTagger:
    return PartOfSpeechTagger(morfeusz_analyser())


class PosHighlighter(QObject):
    """Wybrane części mowy i podświetlenie ich słów w edytorze."""

    def __init__(
        self,
        editor: TranscriptionEditor,
        show_status: Callable[[str], None],
        parent: QObject | None = None,
        tagger_factory: Callable[[], PartOfSpeechTagger] = default_tagger,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._show_status = show_status
        self._tagger_factory = tagger_factory
        self._tagger: PartOfSpeechTagger | None = None
        self._unavailable = False
        self._selected: set[PartOfSpeech] = set()
        self._layer = SpanLayer(editor, POS_LAYER, self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        editor.document().contentsChanged.connect(self._on_text_changed)

    @property
    def selected(self) -> tuple[PartOfSpeech, ...]:
        """Zaznaczone części mowy w kolejności menu (ona rozstrzyga kolor)."""
        return tuple(part for part in PartOfSpeech if part in self._selected)

    def set_part(self, part: PartOfSpeech, enabled: bool) -> None:
        if enabled:
            self._selected.add(part)
        else:
            self._selected.discard(part)
        self.refresh()

    def clear(self) -> None:
        self._selected.clear()
        self.refresh()

    def _on_text_changed(self) -> None:
        if self._selected:
            self._timer.start()

    def _ensure_tagger(self) -> PartOfSpeechTagger | None:
        if self._tagger is None and not self._unavailable:
            try:
                self._tagger = self._tagger_factory()
            except AnalyserUnavailable:
                self._unavailable = True
                self._show_status(tr("highlights.pos.unavailable"))
        return self._tagger

    def refresh(self) -> None:
        """Przelicza słowa zaznaczonych części mowy i odświeża podświetlenia."""
        self._timer.stop()
        wanted = self.selected
        tagger = self._ensure_tagger() if wanted else None
        if tagger is None:
            self._selected.clear()
            self._layer.set_spans([])
            return
        colors = {part: pos_color(part) for part in wanted}
        self._layer.set_spans(
            [
                (start, end, colors[part])
                for start, end, part in tagger.spans(self._editor.plain_text(), wanted)
            ]
        )

    # --- menu „Podświetlenia” ----------------------------------------------

    def fill_menu(self, menu: QMenu) -> None:
        """Części mowy do zaznaczenia (kilka naraz) i wyłączenie wszystkich."""
        menu.addSection(tr("highlights.pos.title"))
        for part in PartOfSpeech:
            action = menu.addAction(swatch(pos_color(part)), tr(f"pos.{part}"))
            action.setCheckable(True)
            action.setChecked(part in self._selected)
            action.setEnabled(not self._unavailable)
            action.setToolTip(
                tr("highlights.pos.unavailable")
                if self._unavailable
                else tr("highlights.pos.tooltip")
            )
            action.toggled.connect(
                lambda checked, chosen=part: self.set_part(chosen, checked)
            )
        off = menu.addAction(tr("highlights.pos.clear"))
        off.setEnabled(bool(self._selected))
        off.triggered.connect(lambda _checked=False: self.clear())
