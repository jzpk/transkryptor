"""Słowa według pytań: filtr widoku i tabela do zapisu (zgłoszenie #72).

Wynik liczy ``document/question_words.py``; tu są tylko rzeczy wspólne dla
kart i tabeli okna: które słowa pokazać (:class:`WordFilter`), nazwy części
mowy i tabela w formacie zapisu CSV/XLSX (:func:`question_words_table`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from transkryptor.corpus.catalog import Table
from transkryptor.document.parts_of_speech import PartOfSpeech
from transkryptor.document.question_words import (
    OUTSIDE,
    QuestionSection,
    QuestionWords,
    SectionWord,
)
from transkryptor.i18n import tr

# Części mowy do wyboru w oknie (wyrazy samodzielne), w kolejności przycisków.
PARTS = (
    PartOfSpeech.NOUN,
    PartOfSpeech.VERB,
    PartOfSpeech.ADJECTIVE,
    PartOfSpeech.ADVERB,
    PartOfSpeech.NUMERAL,
)
ALL_QUESTIONS = -1


@dataclass(frozen=True)
class WordFilter:
    """Co pokazać: sekcja (``ALL_QUESTIONS`` - wszystkie), kolejność, słowa
    spoza pól tematycznych i słowa nierozpoznane."""

    question: int = ALL_QUESTIONS
    alphabetical: bool = False
    outside_fields: bool = False
    unrecognized: bool = True


def part_name(part: PartOfSpeech | None) -> str:
    """Nazwa części mowy w liczbie pojedynczej (None - nierozpoznane)."""
    return tr(f"question_words.part.{part.value if part else 'unknown'}")


def section_title(section: QuestionSection) -> str:
    if section.number == OUTSIDE:
        return tr("question_words.outside")
    return f"{section.number}. {section.question}"


def visible_words(
    section: QuestionSection, words_filter: WordFilter
) -> list[SectionWord]:
    """Słowa sekcji po filtrze, w wybranej kolejności."""
    words = [
        word
        for word in section.words
        if (word.part is not None or words_filter.unrecognized)
        and not (words_filter.outside_fields and word.theme)
    ]
    if words_filter.alphabetical:
        words.sort(key=lambda word: word.lemma.casefold())
    return words


def visible_sections(
    report: QuestionWords, words_filter: WordFilter
) -> list[QuestionSection]:
    return [
        section
        for section in report.sections
        if words_filter.question in (ALL_QUESTIONS, section.number)
    ]


def word_note(word: SectionWord) -> str:
    return tr("question_words.note.ambiguous") if word.ambiguous else ""


def question_words_table(
    sections: Sequence[QuestionSection], words_filter: WordFilter
) -> Table:
    """Tabela słów: numer i treść pytania, słowo, część mowy, liczby i pole."""
    header = tuple(
        tr(f"question_words.column.{name}")
        for name in (
            "number",
            "question",
            "word",
            "part",
            "count",
            "forms",
            "field",
            "speakers",
            "note",
        )
    )
    rows = tuple(
        (
            section.number or "",
            section.question or tr("question_words.outside"),
            word.lemma,
            part_name(word.part),
            word.count,
            ", ".join(word.forms),
            word.theme,
            ", ".join(word.speakers),
            word_note(word),
        )
        for section in sections
        for word in visible_words(section, words_filter)
    )
    return Table(header, rows)
