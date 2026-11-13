"""Zapis szkicu ASR: obróbka tekstu wyniku przed wstawieniem do edytora.

Whisper skraca część wyrażeń („np.”, „tzw.”, „m.in.”), choć w transkrypcji
mają być zapisane tak, jak zostały wypowiedziane (zgłoszenie #42).
:func:`apply_style` rozwija je w tekście segmentów i w słowach (kotwice
czasowe słów zostają). „tzw.” odmienia się zgodnie z następnym słowem przez
funkcję ``agree`` (warstwa UI podaje odmianę Morfeuszem); bez niej - „tak
zwany”. „ok.” jest rozwijane tylko przed liczbą („ok. 20” → „około 20”),
bo bez niej zwykle znaczy „okej”. „itd.” i „itp.” kończące zdanie zachowują
kropkę.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import regex

from transkryptor.asr.engine import SegmentResult, TranscriptionResult

# Skrót → rozwinięcie (bez odmiany). „tzw.” i „ok.” mają reguły osobne.
ABBREVIATIONS: dict[str, str] = {
    "np.": "na przykład",
    "m.in.": "między innymi",
    "itp.": "i tym podobne",
    "itd.": "i tak dalej",
    "tj.": "to jest",
    "tzn.": "to znaczy",
    "wg": "według",
    "zob.": "zobacz",
}
SO_CALLED = "tzw."
ABOUT = "ok."
# Skróty, które zwykle zamykają zdanie - po rozwinięciu zostaje kropka.
SENTENCE_FINAL = frozenset({"itd.", "itp."})

# Forma „zwany” zgodna ze słowem (np. „zwaną” dla „myszkę”); None - nie wiadomo.
Agree = Callable[[str], str | None]

# Słowo z otaczającymi odstępami i interpunkcją: (odstęp)(słowo)(reszta).
_TOKEN_RE = regex.compile(r"(\s*)(\S+?)([,;:!?)\]\"”]*)(?=\s|$)")
_FIRST_LETTER_RE = regex.compile(r"[\p{L}\d]")


@dataclass(frozen=True)
class DraftStyle:
    expand_abbreviations: bool = True
    agree: Agree | None = None


def apply_style(result: TranscriptionResult, style: DraftStyle) -> TranscriptionResult:
    """Wynik ASR z tekstem segmentów i słów przerobionym według ``style``."""
    if not style.expand_abbreviations:
        return result
    segments = tuple(_styled_segment(segment, style) for segment in result.segments)
    text = (
        "".join(segment.text for segment in segments).strip()
        if segments
        else expand_text(result.text, style.agree)
    )
    return replace(result, segments=segments, text=text)


def _styled_segment(segment: SegmentResult, style: DraftStyle) -> SegmentResult:
    tokens = [word.text for word in segment.words]
    expanded = expand_tokens(tokens, style.agree)
    words = tuple(
        replace(word, text=text)
        for word, text in zip(segment.words, expanded, strict=True)
    )
    return replace(segment, text=expand_text(segment.text, style.agree), words=words)


def expand_text(text: str, agree: Agree | None = None) -> str:
    """Tekst z rozwiniętymi skrótami (odstępy między słowami bez zmian)."""
    tokens = [match.group(0) for match in _TOKEN_RE.finditer(text)]
    if "".join(tokens) != text:
        # Nietypowy podział (np. końcowy odstęp) - dokładamy resztę tekstu.
        consumed = sum(len(token) for token in tokens)
        tokens.append(text[consumed:])
    return "".join(expand_tokens(tokens, agree))


def expand_tokens(tokens: Sequence[str], agree: Agree | None = None) -> list[str]:
    """Każde słowo (z odstępem i interpunkcją) z rozwiniętym skrótem."""
    expanded = []
    for index, token in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        expanded.append(_expand_token(token, following, agree))
    return expanded


def _expand_token(token: str, following: str | None, agree: Agree | None) -> str:
    match = _TOKEN_RE.fullmatch(token)
    if match is None:
        return token
    space, word, rest = match.groups()
    expansion = _expansion(word.lower(), following, agree)
    if expansion is None:
        return token
    if word[:1].isupper():
        expansion = expansion[:1].upper() + expansion[1:]
    if not rest and word.lower() in SENTENCE_FINAL and _ends_sentence(following):
        rest = "."
    return space + expansion + rest


def _expansion(word: str, following: str | None, agree: Agree | None) -> str | None:
    next_word = _bare(following)
    if word == SO_CALLED:
        form = agree(next_word) if agree is not None and next_word else None
        return "tak " + (form or "zwany")
    if word == ABOUT:
        return "około" if next_word[:1].isdigit() else None
    return ABBREVIATIONS.get(word)


def _bare(token: str | None) -> str:
    match = _TOKEN_RE.fullmatch(token or "")
    return match.group(2).strip(".") if match else ""


def _ends_sentence(following: str | None) -> bool:
    """Koniec tekstu albo następne słowo wielką literą - skrót kończy zdanie."""
    if following is None or not following.strip():
        return True
    letter = _FIRST_LETTER_RE.search(following)
    return letter is not None and letter.group().isupper()


__all__ = [
    "ABBREVIATIONS",
    "DraftStyle",
    "apply_style",
    "expand_text",
    "expand_tokens",
]
