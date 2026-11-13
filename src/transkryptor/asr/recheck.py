"""Sprawdzenie gotowej transkrypcji według reguł szkicu (zgłoszenie #62).

Transkrypcja zrobiona przed aktualizacją nie przeszła przez obróbkę szkicu,
która doszła w nowszych wersjach, a ponowna transkrypcja nagrania trwa
godzinami i zastąpiłaby poprawki transkrybenta. Ten moduł wyznacza z samego
tekstu to, co szkic zrobiłby dzisiaj - bez modelu ASR:

- :func:`style_suggestions` - zapis szkicu z ustawień (``asr/draft_style.py``:
  skróty w pełnym brzmieniu, zapis mowy) jako propozycje dla pojedynczych
  słów, w tym samym formacie co propozycje reguł fonetycznych
  (``notation.suggestions.Suggestion``) - trafiają na listę przeglądu
  i niczego nie zmieniają bez decyzji użytkownika;
- :func:`question_answer_speakers` - mówcy akapitów bez przypisanego mówcy
  według układu „pytanie - odpowiedź” (``asr/qa_layout.py``): pytanie -
  badacz, reszta - informator.

Propozycje dla słów z indeksem górnym (zapis fonetyczny transkrybenta)
pomija ``ReviewController.review_text`` - zamiana tekstu zgubiłaby format.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from transkryptor.asr.abbreviations import TOKEN_RE, expand_tokens, tokenize
from transkryptor.asr.draft_style import DraftStyle, style_tokens
from transkryptor.i18n import tr
from transkryptor.notation.suggestions import Suggestion

STYLE_CODE = "draft_style"
# Zapis szkicu wynika wprost z ustawień, nie z oceny reguły.
STYLE_CONFIDENCE = 1.0


@dataclass(frozen=True)
class _Paragraph:
    start: int
    text: str


def _paragraphs(text: str) -> Iterator[_Paragraph]:
    start = 0
    for line in text.split("\n"):
        yield _Paragraph(start, line)
        start += len(line) + 1


def style_suggestions(text: str, style: DraftStyle) -> list[Suggestion]:
    """Propozycje zapisu szkicu dla słów ``text`` (każdy akapit osobno)."""
    if not style.changes_text:
        return []
    return [
        suggestion
        for paragraph in _paragraphs(text)
        for suggestion in _paragraph_suggestions(paragraph, style)
    ]


def _paragraph_suggestions(
    paragraph: _Paragraph, style: DraftStyle
) -> Iterator[Suggestion]:
    tokens = tokenize(paragraph.text)
    styled, _ = style_tokens(tokens, style, sentence_start=True)
    expanded = (
        expand_tokens(tokens, style.agree) if style.expand_abbreviations else tokens
    )
    offset = paragraph.start
    for token, after, abbreviation in zip(tokens, styled, expanded, strict=True):
        if token != after:
            yield _suggestion(offset, token, after, abbreviation != token)
        offset += len(token)


def _suggestion(offset: int, token: str, after: str, abbreviation: bool) -> Suggestion:
    """Zamiana całego słowa z interpunkcją (odstęp przed nim zostaje)."""
    match = TOKEN_RE.fullmatch(token)
    space = len(match.group(1)) if match else 0
    kind = "abbreviations" if abbreviation else "speech"
    return Suggestion(
        code=STYLE_CODE,
        start=offset + space,
        end=offset + len(token),
        original=token[space:],
        replacement=after[space:] if after[:space] == token[:space] else after,
        source="style",
        confidence=STYLE_CONFIDENCE,
        message=tr(f"recheck.style.{kind}"),
        word=token[space:],
        word_start=offset + space,
    )


def question_answer_speakers(
    text: str,
    assigned: Mapping[int, str],
    is_question: Callable[[str], bool],
    question_key: str,
    answer_key: str,
) -> dict[int, str]:
    """Mówcy niepustych akapitów bez mówcy: pytanie - ``question_key``.

    Indeksy akapitów jak w ``Document.paragraph_speakers``; akapity
    z mówcą zostają bez zmian.
    """
    return {
        index: question_key if is_question(paragraph.text.strip()) else answer_key
        for index, paragraph in enumerate(_paragraphs(text))
        if index not in assigned and paragraph.text.strip()
    }


__all__ = [
    "STYLE_CODE",
    "question_answer_speakers",
    "style_suggestions",
]
