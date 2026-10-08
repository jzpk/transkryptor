"""Tokenizacja elementów notacji transkrypcji.

Tokeny są potrzebne walidatorowi (faza 01) i późniejszym sugestiom
(faza 04). Pozycje tokenów to półotwarte zakresy znaków ``(start, end)``
w oryginalnym tekście.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TokenKind(Enum):
    """Rodzaje tokenów notacji."""

    WORD = "word"
    PAUSE = "pause"  # " ... " / " … " z odstępem po obu stronach (lub na brzegu)
    CUT_OFF = "cut_off"  # "..." / "…" przylegające do poprzedniego słowa
    ODDITY = "oddity"  # "(!)"
    DOUBT = "doubt"  # "(?)"
    OMITTED = "omitted"  # "[…?]"
    ASIDE_OPEN = "aside_open"  # "["
    ASIDE_CLOSE = "aside_close"  # "]"
    ELLIPSIS = "ellipsis"  # pozostałe "..." lub "…" (np. przed słowem)


@dataclass(frozen=True)
class Token:
    """Token z pozycją w tekście źródłowym."""

    kind: TokenKind
    start: int
    end: int
    text: str


_MARKERS = ("[…?]", "(!)", "(?)")


def tokenize(text: str) -> list[Token]:
    """Dzieli tekst na tokeny notacji, pomijając białe znaki."""
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        matched = False
        for marker in _MARKERS:
            if text.startswith(marker, i):
                kind = {
                    "[…?]": TokenKind.OMITTED,
                    "(!)": TokenKind.ODDITY,
                    "(?)": TokenKind.DOUBT,
                }[marker]
                tokens.append(Token(kind, i, i + len(marker), marker))
                i += len(marker)
                matched = True
                break
        if matched:
            continue
        # Oba zapisy wielokropka (``...`` i ``…``) klasyfikowane są tak samo.
        for ellipsis in ("...", "…"):
            if text.startswith(ellipsis, i):
                end = i + len(ellipsis)
                kind = _classify_ellipsis(text, i, end)
                tokens.append(Token(kind, i, end, ellipsis))
                i = end
                matched = True
                break
        if matched:
            continue
        if text[i] == "[":
            tokens.append(Token(TokenKind.ASIDE_OPEN, i, i + 1, "["))
            i += 1
            continue
        if text[i] == "]":
            tokens.append(Token(TokenKind.ASIDE_CLOSE, i, i + 1, "]"))
            i += 1
            continue
        end = _word_end(text, i)
        tokens.append(Token(TokenKind.WORD, i, end, text[i:end]))
        i = end
    return tokens


def _classify_ellipsis(text: str, i: int, end: int) -> TokenKind:
    """Rozróżnia pauzę od urwanego słowa dla wielokropka ``text[i:end]``."""
    prev_is_word = i > 0 and not text[i - 1].isspace()
    if prev_is_word:
        return TokenKind.CUT_OFF
    if end >= len(text) or text[end].isspace():
        return TokenKind.PAUSE
    return TokenKind.ELLIPSIS


def _word_end(text: str, i: int) -> int:
    """Zwraca koniec ciągu słowa zaczynającego się na pozycji ``i``."""
    n = len(text)
    j = i
    while j < n:
        if text[j].isspace() or text[j] in "[]…":
            break
        if text.startswith("...", j) or any(
            text.startswith(marker, j) for marker in _MARKERS
        ):
            break
        j += 1
    return j
