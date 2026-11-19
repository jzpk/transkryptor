"""Słowa według pytań kwestionariusza (zgłoszenie #72, bez Qt).

Pytania kwestionariusza (``AsrContext.questionnaire``) dzielą wywiad na
odpowiedzi: akapit, w którym badacz zadał pytanie, zaczyna odpowiedź, a
następne odnalezione pytanie ją kończy. Akapit pytania odnajduje
:class:`~transkryptor.document.questionnaire.QuestionMatcher` wśród
wypowiedzi badacza (bez przypisanych mówców - we wszystkich akapitach);
transkrybent może go wskazać ręcznie (:class:`QuestionMark`). Pytania,
których nie odnaleziono, są wypisane osobno, a ich odpowiedzi liczą się do
poprzedniego odnalezionego pytania - sekcja wie, które pytania „wchłonęła”.

W odpowiedziach liczą się słowa informatorów (bez mówców - wszystkie)
wybranych części mowy, sprowadzone do lematu (Morfeusz 2, przez
:class:`~transkryptor.document.parts_of_speech.PartOfSpeechTagger`). Słowo
wieloznaczne ma jedną, najbardziej prawdopodobną część mowy, a w trybie
„pełniejsza lista” (``WordOptions.full``) trafia do każdej, którą może być -
takie wystąpienia są oznaczone (``ambiguous``). Słowa spoza słownika
(formy gwarowe) mają ``part`` None. Przy każdym słowie jest pole tematyczne
(``themes.toml``), jeśli lemat do niego należy - reszta to słownictwo spoza
pól, którego pola tematyczne nie pokazują.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import regex

from transkryptor.document.parts_of_speech import (
    WORD_RE,
    PartOfSpeech,
    PartOfSpeechTagger,
    choose_part,
)
from transkryptor.document.questionnaire import QuestionMark, QuestionMatcher
from transkryptor.document.speakers import Speaker, paragraph_spans
from transkryptor.document.themes import Theme, builtin_themes

# Zdanie akapitu: tekst do znaku końca zdania (włącznie).
_SENTENCE_RE = regex.compile(r"[^.?!…]+[.?!…]*")
CANDIDATES = 5
OUTSIDE = 0  # numer sekcji „poza pytaniami”


@dataclass(frozen=True)
class WordsSource:
    """Transkrypcja z kwestionariuszem; ``name`` - nazwa projektu."""

    name: str
    text: str
    paragraph_speakers: Mapping[int, str] = field(default_factory=dict)
    speakers: Sequence[Speaker] = ()
    questions: tuple[str, ...] = ()
    marks: tuple[QuestionMark, ...] = ()


@dataclass(frozen=True)
class WordOptions:
    """Wybrane części mowy i tryb słów wieloznacznych (``full`` - wszystkie)."""

    parts: frozenset[PartOfSpeech] = frozenset({PartOfSpeech.NOUN})
    full: bool = False


@dataclass(frozen=True)
class QuestionPlace:
    """Akapit pytania w tekście i początek odpowiedzi (pozycja w tekście)."""

    question: int
    paragraph: int
    score: float
    manual: bool
    answer_start: int


@dataclass(frozen=True)
class Candidate:
    """Akapit, który może być pytaniem: numer, tekst i podobieństwo."""

    paragraph: int
    text: str
    score: float


@dataclass(frozen=True)
class SectionWord:
    """Słowo odpowiedzi; ``part`` None - słowo spoza słownika."""

    lemma: str
    part: PartOfSpeech | None
    count: int
    forms: tuple[str, ...]
    speakers: tuple[str, ...]
    theme: str = ""
    ambiguous: bool = False


@dataclass(frozen=True)
class QuestionSection:
    """Odpowiedzi na pytanie (``number`` od 1; ``OUTSIDE`` - poza pytaniami).

    ``place`` i ``asked`` (tekst akapitu pytania) dotyczą bieżącej
    transkrypcji; ``folded`` - numery nieodnalezionych pytań, których
    odpowiedzi mogą być w tej sekcji.
    """

    number: int
    question: str
    words: tuple[SectionWord, ...]
    place: QuestionPlace | None = None
    asked: str = ""
    folded: tuple[int, ...] = ()


@dataclass(frozen=True)
class UnlocatedQuestion:
    """Pytanie bez akapitu; odpowiedzi liczą się do sekcji ``folded_into``."""

    number: int
    question: str
    folded_into: int


@dataclass(frozen=True)
class QuestionWords:
    """Wynik: sekcje w kolejności tekstu, pytania nieodnalezione i wskazania,
    których akapitu już nie ma w tekście (``lost_marks``)."""

    sections: tuple[QuestionSection, ...]
    unlocated: tuple[UnlocatedQuestion, ...] = ()
    lost_marks: tuple[QuestionMark, ...] = ()


# --- pytania w tekście ---------------------------------------------------------


class QuestionLocator:
    """Akapity pytań jednej transkrypcji (odnalezione i wskazane ręcznie)."""

    def __init__(self, source: WordsSource) -> None:
        self.source = source
        self.spans = paragraph_spans(source.text)
        self._matcher = QuestionMatcher(source.questions)
        informants = {s.key for s in source.speakers if s.is_informant}
        self.has_speakers = bool(source.paragraph_speakers)
        self.informant_paragraphs = frozenset(
            index
            for index, key in source.paragraph_speakers.items()
            if key in informants
        )

    def paragraph_text(self, index: int) -> str:
        start, end = self.spans[index]
        return self.source.text[start:end]

    def asking_paragraphs(self) -> list[int]:
        """Akapity, w których badacz może zadać pytanie."""
        return [
            index
            for index in range(len(self.spans))
            if index not in self.informant_paragraphs
            and self.paragraph_text(index).strip()
        ]

    def _best_sentence(
        self, index: int, question: int | None = None
    ) -> tuple[int, float, int] | None:
        """(pytanie, podobieństwo, koniec zdania) najlepszego zdania akapitu."""
        start, _ = self.spans[index]
        found: tuple[int, float, int] | None = None
        for match in _SENTENCE_RE.finditer(self.paragraph_text(index)):
            sentence = match.group()
            if question is None:
                best = self._matcher.best(sentence)
            else:
                best = (question, self._matcher.similarity(sentence, question))
            if best is not None and (found is None or best[1] > found[1]):
                found = (best[0], best[1], start + match.end())
        return found

    def _answer_start(self, index: int, sentence_end: int) -> int:
        # Z mówcami odpowiedź to następne akapity informatorów; bez mówców
        # zaczyna się tuż po zdaniu z pytaniem.
        return self.spans[index][1] if self.has_speakers else sentence_end

    def locate(self) -> tuple[dict[int, QuestionPlace], tuple[QuestionMark, ...]]:
        """Akapity pytań (numer pytania od 0 → miejsce) i wskazania bez akapitu."""
        places: dict[int, QuestionPlace] = {}
        for index in self.asking_paragraphs():
            best = self._best_sentence(index)
            if best is None:
                continue
            question, score, end = best
            if question not in places or score > places[question].score:
                places[question] = QuestionPlace(
                    question, index, score, False, self._answer_start(index, end)
                )
        lost: list[QuestionMark] = []
        for mark in self.source.marks:
            place = self._marked(mark)
            if place is None:
                lost.append(mark)
                continue
            places = {
                key: value
                for key, value in places.items()
                if value.paragraph != place.paragraph
            }
            places[mark.question] = place
        return places, tuple(lost)

    def _marked(self, mark: QuestionMark) -> QuestionPlace | None:
        wanted = mark.paragraph.strip()
        if not wanted or not 0 <= mark.question < len(self.source.questions):
            return None
        for index in range(len(self.spans)):
            if self.paragraph_text(index).strip() == wanted:
                best = self._best_sentence(index, mark.question)
                score, end = (best[1], best[2]) if best else (0.0, self.spans[index][1])
                return QuestionPlace(
                    mark.question, index, score, True, self._answer_start(index, end)
                )
        return None

    def candidates(self, question: int, limit: int = CANDIDATES) -> list[Candidate]:
        """Akapity najbardziej podobne do pytania (do ręcznego wskazania)."""
        scored = []
        for index in self.asking_paragraphs():
            best = self._best_sentence(index, question)
            if best is not None and best[1] > 0:
                scored.append(Candidate(index, self.paragraph_text(index), best[1]))
        scored.sort(key=lambda candidate: (-candidate.score, candidate.paragraph))
        return scored[:limit]

    def answer_ranges(self, start: int, end: int) -> list[tuple[int, int]]:
        """Zakresy odpowiedzi w ``[start, end)`` - z mówcami tylko informatorzy."""
        if not self.has_speakers:
            return [(start, end)] if start < end else []
        ranges = []
        for index in sorted(self.informant_paragraphs):
            span_start, span_end = self.spans[index]
            low, high = max(span_start, start), min(span_end, end)
            if low < high:
                ranges.append((low, high))
        return ranges

    def speaker_of(self, position: int) -> str:
        """Nazwa informatora akapitu z pozycją (jak w polach tematycznych)."""
        index = self.source.text.count("\n", 0, position)
        key = self.source.paragraph_speakers.get(index)
        for speaker in self.source.speakers:
            if speaker.key == key:
                return speaker.label or f"{key} ({self.source.name})"
        return self.source.name


# --- liczenie słów -------------------------------------------------------------


class _Tally:
    """Lematy jednej sekcji: wystąpienia, formy, informatorzy, wieloznaczność."""

    def __init__(self) -> None:
        self.counts: dict[tuple[PartOfSpeech | None, str], int] = defaultdict(int)
        self.lemmas: dict[tuple[PartOfSpeech | None, str], str] = {}
        self.forms: dict[tuple[PartOfSpeech | None, str], dict[str, None]] = (
            defaultdict(dict)
        )
        self.speakers: dict[tuple[PartOfSpeech | None, str], dict[str, None]] = (
            defaultdict(dict)
        )
        self.certain: set[tuple[PartOfSpeech | None, str]] = set()

    def add(
        self, part: PartOfSpeech | None, lemma: str, form: str, speaker: str, sure: bool
    ) -> None:
        key = (part, lemma.casefold())
        self.counts[key] += 1
        self.lemmas.setdefault(key, lemma)
        self.forms[key].setdefault(form.casefold())
        self.speakers[key].setdefault(speaker)
        if sure:
            self.certain.add(key)

    def merge(self, other: _Tally) -> None:
        for key, count in other.counts.items():
            self.counts[key] += count
            self.lemmas.setdefault(key, other.lemmas[key])
            self.forms[key].update(other.forms[key])
            self.speakers[key].update(other.speakers[key])
        self.certain |= other.certain

    def words(self, themes: Mapping[str, str]) -> tuple[SectionWord, ...]:
        ranked = sorted(self.counts.items(), key=lambda item: (-item[1], item[0][1]))
        return tuple(
            SectionWord(
                self.lemmas[key],
                key[0],
                count,
                tuple(self.forms[key]),
                tuple(speaker for speaker in self.speakers[key] if speaker),
                themes.get(key[1], "") if key[0] is not None else "",
                key not in self.certain,
            )
            for key, count in ranked
        )


def _readings_for(
    tagger: PartOfSpeechTagger, word: str, options: WordOptions
) -> list[tuple[PartOfSpeech | None, str, bool]]:
    """(część mowy, lemat, pewne) - jak słowo liczy się przy tych opcjach."""
    readings = tagger.readings(word)
    if not readings:
        return [(None, word, True)]
    chosen = choose_part(readings)
    found: list[tuple[PartOfSpeech | None, str, bool]] = []
    for part in dict.fromkeys(part for part, _ in readings):
        if part not in options.parts or (part is not chosen and not options.full):
            continue
        lemma = next(lemma for reading, lemma in readings if reading is part)
        found.append((part, lemma, part is chosen))
    return found


def _count(
    locator: QuestionLocator,
    ranges: Iterable[tuple[int, int]],
    tagger: PartOfSpeechTagger,
    options: WordOptions,
) -> _Tally:
    tally = _Tally()
    text = locator.source.text
    for start, end in ranges:
        speaker = locator.speaker_of(start)
        for match in WORD_RE.finditer(text, start, end):
            word = match.group()
            for part, lemma, sure in _readings_for(tagger, word, options):
                tally.add(part, lemma, word, speaker, sure)
    return tally


def theme_labels(themes: Iterable[Theme] | None = None) -> dict[str, str]:
    """Lemat (casefold) → nazwa pierwszego pola tematycznego, do którego należy."""
    labels: dict[str, str] = {}
    for theme in builtin_themes() if themes is None else themes:
        for lemma in theme.lemmas:
            labels.setdefault(lemma, theme.label_text)
    return labels


# --- sekcje --------------------------------------------------------------------


@dataclass
class _Section:
    number: int
    question: str
    tally: _Tally
    place: QuestionPlace | None = None
    asked: str = ""
    folded: list[int] = field(default_factory=list)


def _source_sections(
    source: WordsSource, tagger: PartOfSpeechTagger, options: WordOptions
) -> tuple[list[_Section], list[UnlocatedQuestion], tuple[QuestionMark, ...]]:
    locator = QuestionLocator(source)
    places, lost = locator.locate()
    ordered = sorted(places.values(), key=lambda p: (p.paragraph, p.answer_start))
    text = source.text
    sections: list[_Section] = []
    first = locator.spans[ordered[0].paragraph][0] if ordered else len(text)
    outside = _count(locator, locator.answer_ranges(0, first), tagger, options)
    if outside.counts:
        sections.append(_Section(OUTSIDE, "", outside))
    for position, place in enumerate(ordered):
        following = ordered[position + 1] if position + 1 < len(ordered) else None
        end = locator.spans[following.paragraph][0] if following else len(text)
        ranges = locator.answer_ranges(place.answer_start, end)
        sections.append(
            _Section(
                place.question + 1,
                source.questions[place.question],
                _count(locator, ranges, tagger, options),
                place,
                locator.paragraph_text(place.paragraph).strip(),
            )
        )
    unlocated = []
    by_number = {section.number: section for section in sections}
    for index, question in enumerate(source.questions):
        if index in places:
            continue
        earlier = [q for q in places if q < index]
        target = max(earlier) + 1 if earlier else OUTSIDE
        unlocated.append(UnlocatedQuestion(index + 1, question, target))
        if target in by_number:
            by_number[target].folded.append(index + 1)
    return sections, unlocated, lost


def _question_key(question: str) -> str:
    return " ".join(regex.findall(r"\p{L}+", question.casefold()))


def question_words(
    sources: Sequence[WordsSource],
    tagger: PartOfSpeechTagger,
    options: WordOptions = WordOptions(),
    themes: Iterable[Theme] | None = None,
) -> QuestionWords:
    """Słowa według pytań: pierwsze źródło to bieżąca transkrypcja.

    Odpowiedzi na to samo pytanie (ta sama treść) z kilku transkrypcji
    łączą się w jedną sekcję; miejsca pytań, pytania nieodnalezione
    i wskazania bez akapitu dotyczą pierwszego źródła.
    """
    labels = theme_labels(themes)
    merged: dict[str, _Section] = {}
    unlocated: list[UnlocatedQuestion] = []
    lost: tuple[QuestionMark, ...] = ()
    for position, source in enumerate(sources):
        sections, missing, lost_marks = _source_sections(source, tagger, options)
        if position == 0:
            unlocated, lost = missing, lost_marks
        for section in sections:
            key = _question_key(section.question)
            if key in merged:
                merged[key].tally.merge(section.tally)
            else:
                if position:
                    section.place, section.asked, section.folded = None, "", []
                merged[key] = section
    return QuestionWords(
        tuple(
            QuestionSection(
                section.number,
                section.question,
                section.tally.words(labels),
                section.place,
                section.asked,
                tuple(section.folded),
            )
            for section in merged.values()
        ),
        tuple(unlocated),
        lost,
    )


__all__ = [
    "OUTSIDE",
    "Candidate",
    "QuestionLocator",
    "QuestionPlace",
    "QuestionSection",
    "QuestionWords",
    "SectionWord",
    "UnlocatedQuestion",
    "WordOptions",
    "WordsSource",
    "question_words",
    "theme_labels",
]
