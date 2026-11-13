"""Zapis szkicu ASR: obróbka tekstu wyniku przed wstawieniem do edytora.

Dwa kroki, oba opcjonalne (``DraftStyle``):

1. Skróty w pełnym brzmieniu (``asr/abbreviations.py``, zgłoszenie #42).
2. Zapis mowy (zgłoszenie #37): pierwsze słowo zdania małą literą i bez
   przecinków, kropek, średników i dwukropków - zostają znaki zapytania,
   wykrzykniki i wielokropki. Nazwy własne zostają wielką literą: o tym, czy
   słowo może nią być, decyduje ``may_be_proper`` (warstwa UI podaje
   Morfeusza); słowa wielkimi literami w środku zdania i skrótowce („PRL”)
   nie są zmieniane. Kropka między cyframi („1.5”) zostaje.

:func:`apply_style` przerabia tak samo tekst segmentów i ich słowa (słowo po
słowie, ze stanem „początek zdania” przechodzącym między segmentami), więc
kotwice czasowe słów nadal pasują do tekstu szkicu.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import regex

from transkryptor.asr.abbreviations import TOKEN_RE, Agree, expand_tokens, tokenize
from transkryptor.asr.engine import SegmentResult, TranscriptionResult

# Interpunkcja usuwana w zapisie mowy (zostają ? ! i wielokropki).
_DROPPED = str.maketrans("", "", ",;:")
_ELLIPSES = ("...", "…")
# Znaki kończące zdanie (po nich słowo małą literą); zamykające cudzysłowy
# i nawiasy za nimi nie przeszkadzają.
_SENTENCE_END_RE = regex.compile(r"(?:[.!?…])[\"”)\]]*$")
_LETTERS_RE = regex.compile(r"\p{L}+")


@dataclass(frozen=True)
class DraftStyle:
    expand_abbreviations: bool = True
    lowercase_plain: bool = False
    agree: Agree | None = None
    may_be_proper: Callable[[str], bool] | None = None

    @property
    def changes_text(self) -> bool:
        return self.expand_abbreviations or self.lowercase_plain


def apply_style(result: TranscriptionResult, style: DraftStyle) -> TranscriptionResult:
    """Wynik ASR z tekstem segmentów i słów przerobionym według ``style``."""
    if not style.changes_text:
        return result
    if not result.segments:
        return replace(result, text=style_text(result.text, style).strip())
    segments = []
    sentence_start = True
    for segment in result.segments:
        styled, next_start = _styled_segment(segment, style, sentence_start)
        segments.append(styled)
        sentence_start = next_start
    text = "".join(segment.text for segment in segments).strip()
    return replace(result, segments=tuple(segments), text=text)


def style_text(text: str, style: DraftStyle) -> str:
    """Sam tekst (np. szkic bez segmentów) przerobiony według ``style``."""
    tokens, _ = style_tokens(tokenize(text), style, sentence_start=True)
    return "".join(tokens)


def style_tokens(
    tokens: Sequence[str], style: DraftStyle, *, sentence_start: bool
) -> tuple[list[str], bool]:
    """Słowa po obu krokach i czy następne słowo zaczyna zdanie."""
    result = list(tokens)
    if style.expand_abbreviations:
        result = expand_tokens(result, style.agree)
    if style.lowercase_plain:
        result, sentence_start = _plain_tokens(result, sentence_start, style)
    return result, sentence_start


def _styled_segment(
    segment: SegmentResult, style: DraftStyle, sentence_start: bool
) -> tuple[SegmentResult, bool]:
    text_tokens, next_start = style_tokens(
        tokenize(segment.text), style, sentence_start=sentence_start
    )
    word_tokens, _ = style_tokens(
        [word.text for word in segment.words], style, sentence_start=sentence_start
    )
    words = tuple(
        replace(word, text=text)
        for word, text in zip(segment.words, word_tokens, strict=True)
    )
    return replace(segment, text="".join(text_tokens), words=words), next_start


def _plain_tokens(
    tokens: Sequence[str], sentence_start: bool, style: DraftStyle
) -> tuple[list[str], bool]:
    result = []
    for token in tokens:
        # Rozwinięty skrót bywa kilkoma słowami w jednym słowie Whispera.
        pieces = []
        for piece in tokenize(token) or [token]:
            styled, sentence_start = _plain_piece(piece, sentence_start, style)
            pieces.append(styled)
        result.append("".join(pieces))
    return result, sentence_start


def _plain_piece(
    token: str, sentence_start: bool, style: DraftStyle
) -> tuple[str, bool]:
    match = TOKEN_RE.fullmatch(token)
    if match is None:
        return token, sentence_start
    space, word, rest = match.groups()
    ends = bool(_SENTENCE_END_RE.search(word + rest))
    rest = rest.translate(_DROPPED)
    if not word.endswith(_ELLIPSES):
        word = word.rstrip(".")
    if sentence_start:
        word = _lower_first(word, style.may_be_proper)
    if not _LETTERS_RE.search(word):
        # Sama interpunkcja nie zaczyna zdania od nowa.
        return space + word + rest, sentence_start or ends
    return space + word + rest, ends


def _lower_first(word: str, may_be_proper: Callable[[str], bool] | None) -> str:
    letters = _LETTERS_RE.search(word)
    if letters is None or not letters.group()[0].isupper():
        return word
    bare = letters.group()
    if len(bare) > 1 and bare.isupper():
        return word  # skrótowiec, np. „PRL”
    if may_be_proper is not None and may_be_proper(bare):
        return word
    index = letters.start()
    return word[:index] + word[index].lower() + word[index + 1 :]


__all__ = ["DraftStyle", "apply_style", "style_text", "style_tokens"]
