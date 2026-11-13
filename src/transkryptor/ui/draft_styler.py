"""Zapis szkicu ASR według ustawień, z pomocą Morfeusza 2.

Łączy czystą obróbkę tekstu (``asr/draft_style.py``) z ustawieniami,
odmianą „tak zwany” zgodną z następnym słowem i rozpoznawaniem nazw
własnych (zostają wielką literą w zapisie małymi literami). Morfeusz jest
wczytywany przy pierwszym szkicu; bez niego „tzw.” rozwija się do „tak
zwany”, a pierwsze słowo zdania zawsze trafia małą literą.
"""

from __future__ import annotations

from collections.abc import Callable

from transkryptor.asr.draft_style import DraftStyle, apply_style, style_text
from transkryptor.asr.engine import TranscriptionResult
from transkryptor.document.inflection import Inflector, morfeusz_inflector
from transkryptor.document.parts_of_speech import AnalyserUnavailable
from transkryptor.document.proper_names import ProperNames, morfeusz_proper_names
from transkryptor.settings import AsrSettings

# Lemat imiesłowu w rozwinięciu „tzw.” („tak zwany/zwaną…”).
SO_CALLED_LEMMA = "zwać"


class DraftStyler:
    """Wynik ASR albo tekst szkicu przerobiony według bieżących ustawień."""

    def __init__(
        self,
        settings: Callable[[], AsrSettings],
        inflector_factory: Callable[[], Inflector] = morfeusz_inflector,
        names_factory: Callable[[], ProperNames] = morfeusz_proper_names,
    ) -> None:
        self._settings = settings
        self._inflector_factory = inflector_factory
        self._names_factory = names_factory
        self._inflector: Inflector | None = None
        self._names: ProperNames | None = None
        self._unavailable = False

    def style(self) -> DraftStyle:
        asr = self._settings()
        return DraftStyle(
            expand_abbreviations=asr.expand_abbreviations,
            lowercase_plain=asr.lowercase_plain,
            agree=self._agree,
            may_be_proper=self._may_be_proper,
        )

    def apply(self, result: TranscriptionResult) -> TranscriptionResult:
        return apply_style(result, self.style())

    def apply_text(self, text: str) -> str:
        return style_text(text, self.style())

    def _load(self) -> None:
        if self._inflector is None and not self._unavailable:
            try:
                self._inflector = self._inflector_factory()
                self._names = self._names_factory()
            except AnalyserUnavailable:
                self._unavailable = True

    def _agree(self, word: str) -> str | None:
        self._load()
        if self._inflector is None:
            return None
        return self._inflector.agreeing(SO_CALLED_LEMMA, word)

    def _may_be_proper(self, word: str) -> bool:
        self._load()
        return self._names is not None and self._names.may_be_proper(word)
