"""Porównanie dwóch wersji transkrypcji na poziomie słów (bez Qt).

Wersja to tekst z zakresami indeksu górnego i mówcami akapitów
(:class:`Version`). :func:`diff_versions` porównuje tokeny — słowa, odstępy
i znaki nowej linii osobno, więc granice akapitów są zachowane —
``difflib.SequenceMatcher`` i zwraca listę zmian (:class:`Change`):
wstawienie, usunięcie, zmianę tekstu, zmianę indeksu górnego w słowie
o tym samym tekście i zmianę mówcy akapitu. Wersja A to dokument bieżący
(wynik porównania), wersja B — porównywana; zakresy zmian są w obu
wersjach.

:func:`fragment` daje tekst zmiany z formatowaniem i mówcami akapitów,
które fragment zaczyna — tyle trzeba, by przyjąć zmianę z B albo ją
cofnąć. :func:`apply_change` to referencyjne przyjęcie zmiany w modelu
(testy i sprawdzenie wyniku edytora).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from transkryptor.document.model import Document, normalize_ranges
from transkryptor.document.speakers import paragraph_spans, shift_assignments

INSERT = "insert"
DELETE = "delete"
REPLACE = "replace"
FORMAT = "format"
SPEAKER = "speaker"
KINDS = (INSERT, DELETE, REPLACE, FORMAT, SPEAKER)

# Nowa linia, odstęp bez nowej linii albo słowo (ciąg znaków niebiałych).
_TOKEN_RE = re.compile(r"\n|[^\S\n]+|\S+")


@dataclass(frozen=True)
class Version:
    """Tekst z indeksem górnym i mówcami akapitów (indeks akapitu → klucz)."""

    text: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    paragraph_speakers: Mapping[int, str] = field(default_factory=dict)

    @classmethod
    def from_document(cls, document: Document) -> Version:
        return cls(
            document.text,
            tuple(document.superscript_ranges),
            dict(document.paragraph_speakers),
        )


@dataclass(frozen=True)
class Fragment:
    """Fragment wersji: tekst, zakresy indeksu górnego względem jego początku
    i mówcy akapitów, które fragment zaczyna (po każdym ``\\n``).

    ``lead`` to mówca akapitu, w którym fragment się zaczyna, a
    ``at_paragraph_start`` — czy zaczyna się na początku akapitu.
    """

    text: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    speakers: tuple[str | None, ...] = ()
    lead: str | None = None
    at_paragraph_start: bool = False


@dataclass(frozen=True)
class Change:
    """Zmiana ``a.text[a_start:a_end]`` → ``b.text[b_start:b_end]``.

    Wstawienie ma pusty zakres w A, usunięcie — w B. Dla zmiany mówcy
    zakresy obejmują akapit, a ``a_speaker``/``b_speaker`` to klucze
    mówców (None — akapit bez mówcy).
    """

    kind: str
    a_start: int
    a_end: int
    b_start: int
    b_end: int
    a_speaker: str | None = None
    b_speaker: str | None = None


def _tokens(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _TOKEN_RE.finditer(text)]


def _mask(ranges: Iterable[tuple[int, int]], start: int, end: int) -> frozenset[int]:
    """Pozycje (względem ``start``) znaków z indeksem górnym w ``[start, end)``."""
    return frozenset(
        position - start
        for range_start, range_end in ranges
        for position in range(max(range_start, start), min(range_end, end))
    )


def _starts_paragraph(text: str, position: int) -> bool:
    return position == 0 or text[position - 1] == "\n"


def diff_versions(a: Version, b: Version) -> list[Change]:
    """Zmiany potrzebne, by z wersji A otrzymać wersję B (posortowane w A)."""
    a_tokens = _tokens(a.text)
    b_tokens = _tokens(b.text)
    matcher = SequenceMatcher(
        None,
        [a.text[s:e] for s, e in a_tokens],
        [b.text[s:e] for s, e in b_tokens],
        autojunk=False,
    )
    changes: list[Change] = []
    # Pary akapitów (A, B), które zaczynają się tym samym niezmienionym
    # tokenem — tylko dla nich porównujemy mówców.
    paragraphs: list[tuple[int, int]] = []

    def char_span(
        tokens: list[tuple[int, int]], first: int, last: int, length: int
    ) -> tuple[int, int]:
        if first == last:
            position = tokens[first][0] if first < len(tokens) else length
            return position, position
        return tokens[first][0], tokens[last - 1][1]

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for a_token, b_token in zip(a_tokens[i1:i2], b_tokens[j1:j2], strict=True):
                if _starts_paragraph(a.text, a_token[0]) and _starts_paragraph(
                    b.text, b_token[0]
                ):
                    paragraphs.append(
                        (
                            a.text.count("\n", 0, a_token[0]),
                            b.text.count("\n", 0, b_token[0]),
                        )
                    )
                if a.text[a_token[0]] == "\n":
                    continue
                if _mask(a.superscript_ranges, *a_token) != _mask(
                    b.superscript_ranges, *b_token
                ):
                    changes.append(Change(FORMAT, *a_token, *b_token))
            continue
        a_start, a_end = char_span(a_tokens, i1, i2, len(a.text))
        b_start, b_end = char_span(b_tokens, j1, j2, len(b.text))
        kind = INSERT if a_start == a_end else DELETE if b_start == b_end else REPLACE
        changes.append(Change(kind, a_start, a_end, b_start, b_end))

    # Pusty ostatni akapit nie ma tokenu: para, gdy obie wersje kończą się
    # niezmienionym znakiem nowej linii (albo obie są puste).
    if (not a.text and not b.text) or (
        a.text.endswith("\n")
        and b.text.endswith("\n")
        and matcher.get_opcodes()[-1][0] == "equal"
    ):
        paragraphs.append((a.text.count("\n"), b.text.count("\n")))
    a_spans = paragraph_spans(a.text)
    b_spans = paragraph_spans(b.text)
    for a_index, b_index in paragraphs:
        a_key = a.paragraph_speakers.get(a_index)
        b_key = b.paragraph_speakers.get(b_index)
        if a_key != b_key:
            changes.append(
                Change(SPEAKER, *a_spans[a_index], *b_spans[b_index], a_key, b_key)
            )
    changes.sort(key=lambda change: (change.a_start, change.kind == SPEAKER))
    return changes


def fragment(version: Version, start: int, end: int) -> Fragment:
    """Fragment ``version.text[start:end]`` z formatowaniem i mówcami."""
    text = version.text[start:end]
    ranges = normalize_ranges(
        [
            (max(s, start) - start, min(e, end) - start)
            for s, e in version.superscript_ranges
            if s < end and e > start
        ]
    )
    first = version.text.count("\n", 0, start)
    speakers = tuple(
        version.paragraph_speakers.get(first + offset)
        for offset in range(1, text.count("\n") + 1)
    )
    return Fragment(
        text,
        tuple(ranges),
        speakers,
        version.paragraph_speakers.get(first),
        _starts_paragraph(version.text, start),
    )


def apply_change(a: Version, b: Version, change: Change) -> Version:
    """Wersja A po przyjęciu zmiany z B (referencja dla edytora)."""
    if change.kind == SPEAKER:
        index = a.text.count("\n", 0, change.a_start)
        speakers = dict(a.paragraph_speakers)
        if change.b_speaker is None:
            speakers.pop(index, None)
        else:
            speakers[index] = change.b_speaker
        return Version(a.text, a.superscript_ranges, speakers)
    return replace_fragment(
        a, change.a_start, change.a_end, fragment(b, change.b_start, change.b_end)
    )


def replace_fragment(version: Version, start: int, end: int, new: Fragment) -> Version:
    """Wersja z ``text[start:end]`` zastąpionym fragmentem (z jego formatem)."""
    text = version.text[:start] + new.text + version.text[end:]
    delta = len(new.text) - (end - start)
    ranges: list[tuple[int, int]] = []
    for s, e in version.superscript_ranges:
        if e <= start:
            ranges.append((s, e))
        elif s >= end:
            ranges.append((s + delta, e + delta))
        else:
            if s < start:
                ranges.append((s, start))
            if e > end:
                ranges.append((end + delta, e + delta))
    ranges.extend((start + s, start + e) for s, e in new.superscript_ranges)
    first = version.text.count("\n", 0, start)
    speakers = shift_assignments(
        version.paragraph_speakers, version.text[start:end], new.text, first
    )
    for offset, key in enumerate(replaced_speakers(version, start, end, new)):
        if key is None:
            speakers.pop(first + offset, None)
        else:
            speakers[first + offset] = key
    return Version(text, tuple(normalize_ranges(ranges)), speakers)


def replaced_speakers(
    version: Version, start: int, end: int, new: Fragment
) -> list[str | None]:
    """Mówcy akapitów, które zastąpienie ``text[start:end]`` tworzy albo scala.

    Kolejno: akapit zawierający ``start`` i akapity zaczęte przez fragment.
    Zmiana bez znaków nowej linii nie rusza mówców. Gdy zmiana dzieli albo
    scala akapity od początku akapitu, pierwszy akapit wyniku zaczyna się
    tekstem fragmentu (i dostaje jego mówcę), a przy samym usunięciu —
    tekstem ostatniego scalonego akapitu (który zachowuje swojego mówcę).
    """
    removed = version.text[start:end]
    first = version.text.count("\n", 0, start)
    lead = version.paragraph_speakers.get(first)
    if ("\n" in removed or "\n" in new.text) and _starts_paragraph(version.text, start):
        if not new.text.split("\n", 1)[0] and "\n" in removed:
            lead = version.paragraph_speakers.get(first + removed.count("\n"))
        elif new.at_paragraph_start:
            lead = new.lead
    return [lead, *new.speakers]
