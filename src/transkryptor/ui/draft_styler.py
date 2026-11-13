"""Zapis szkicu ASR według ustawień, z odmianą Morfeuszem 2.

Łączy czystą obróbkę tekstu (``asr/draft_style.py``) z ustawieniami
i odmianą „tak zwany” zgodną z następnym słowem. Morfeusz jest wczytywany
przy pierwszym szkicu; bez niego „tzw.” rozwija się do „tak zwany”.
"""

from __future__ import annotations

from collections.abc import Callable

from transkryptor.asr.draft_style import DraftStyle, apply_style, expand_text
from transkryptor.asr.engine import TranscriptionResult
from transkryptor.document.inflection import Inflector, morfeusz_inflector
from transkryptor.document.parts_of_speech import AnalyserUnavailable
from transkryptor.settings import AsrSettings

# Lemat imiesłowu w rozwinięciu „tzw.” („tak zwany/zwaną…”).
SO_CALLED_LEMMA = "zwać"


class DraftStyler:
    """Wynik ASR albo tekst szkicu przerobiony według bieżących ustawień."""

    def __init__(
        self,
        settings: Callable[[], AsrSettings],
        inflector_factory: Callable[[], Inflector] = morfeusz_inflector,
    ) -> None:
        self._settings = settings
        self._inflector_factory = inflector_factory
        self._inflector: Inflector | None = None
        self._unavailable = False

    def style(self) -> DraftStyle:
        asr = self._settings()
        return DraftStyle(
            expand_abbreviations=asr.expand_abbreviations, agree=self._agree
        )

    def apply(self, result: TranscriptionResult) -> TranscriptionResult:
        return apply_style(result, self.style())

    def apply_text(self, text: str) -> str:
        style = self.style()
        return expand_text(text, style.agree) if style.expand_abbreviations else text

    def _agree(self, word: str) -> str | None:
        if self._inflector is None and not self._unavailable:
            try:
                self._inflector = self._inflector_factory()
            except AnalyserUnavailable:
                self._unavailable = True
        if self._inflector is None:
            return None
        return self._inflector.agreeing(SO_CALLED_LEMMA, word)
