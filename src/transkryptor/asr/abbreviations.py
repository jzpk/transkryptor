"""Skróty Whispera w pełnym brzmieniu (zgłoszenie #42).

Whisper skraca część wyrażeń („np.”, „tzw.”, „m.in.”), choć w transkrypcji
mają być zapisane tak, jak zostały wypowiedziane. „tzw.” odmienia się
zgodnie z następnym słowem przez funkcję ``agree`` (warstwa UI podaje
odmianę Morfeuszem); bez niej - „tak zwany”. „ok.” jest rozwijane tylko
przed liczbą („ok. 20” → „około 20”), bo bez niej zwykle znaczy „okej”.
„itd.” i „itp.” kończące zdanie zachowują kropkę.

Tekst jest dzielony na słowa razem z odstępem przed nimi i interpunkcją
po nich (:func:`tokenize`), tak jak słowa Whispera (``" kota,"``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import regex

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
TOKEN_RE = regex.compile(r"(\s*)(\S+?)([,;:!?)\]\"”]*)(?=\s|$)")
_FIRST_LETTER_RE = regex.compile(r"[\p{L}\d]")


def tokenize(text: str) -> list[str]:
    """Słowa tekstu z odstępem przed nimi i interpunkcją po nich (bez strat)."""
    tokens = [match.group(0) for match in TOKEN_RE.finditer(text)]
    consumed = sum(len(token) for token in tokens)
    if consumed != len(text):
        # Nietypowy podział (np. końcowy odstęp) - dokładamy resztę tekstu.
        tokens.append(text[consumed:])
    return tokens


def expand_text(text: str, agree: Agree | None = None) -> str:
    """Tekst z rozwiniętymi skrótami (odstępy między słowami bez zmian)."""
    return "".join(expand_tokens(tokenize(text), agree))


def expand_tokens(tokens: Sequence[str], agree: Agree | None = None) -> list[str]:
    """Każde słowo (z odstępem i interpunkcją) z rozwiniętym skrótem."""
    expanded = []
    for index, token in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        expanded.append(_expand_token(token, following, agree))
    return expanded


def _expand_token(token: str, following: str | None, agree: Agree | None) -> str:
    match = TOKEN_RE.fullmatch(token)
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
    match = TOKEN_RE.fullmatch(token or "")
    return match.group(2).strip(".") if match else ""


def _ends_sentence(following: str | None) -> bool:
    """Koniec tekstu albo następne słowo wielką literą - skrót kończy zdanie."""
    if following is None or not following.strip():
        return True
    letter = _FIRST_LETTER_RE.search(following)
    return letter is not None and letter.group().isupper()
