"""Konkordancja: trafienia wyszukiwania we wszystkich projektach (bez Qt).

Trafienie to zakres tekstu projektu z kontekstem z lewej i prawej strony
(w obrębie akapitu - wypowiedzi jednego mówcy), mówcą akapitu i czasem
fragmentu w nagraniu z kotwic czasowych (gdy są). Zapytanie kompiluje
``document/search.py`` - te same opcje i ta sama składnia co w pasku
wyszukiwania, z limitem czasu na każdy projekt.

Teksty trafień i kontekstu zapisują indeks górny składnią zamiennika
(``be^ndzie``), tak jak słownik form - różnica zapisu jest widoczna.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import regex

from transkryptor.corpus.projects import CorpusProject
from transkryptor.document.anchors import time_span
from transkryptor.document.search import find_all, restrict_to
from transkryptor.document.speakers import informant_spans, paragraph_spans

# Znaki kontekstu po każdej stronie trafienia.
CONTEXT_CHARS = 60
# Łączny limit trafień (lista w oknie i odsłuch pozostają płynne).
MAX_HITS = 5000
ELLIPSIS = "…"


@dataclass(frozen=True)
class Hit:
    project: CorpusProject
    start: int
    end: int
    left: str
    match: str
    right: str
    speaker: str = ""
    time_ms: tuple[int, int] | None = None


@dataclass(frozen=True)
class Concordance:
    hits: tuple[Hit, ...]
    # Trafień było więcej niż ``MAX_HITS`` - lista jest ucięta.
    truncated: bool = False

    @property
    def project_count(self) -> int:
        return len({id(hit.project) for hit in self.hits})


def marked_text(
    text: str, superscript_ranges: Sequence[tuple[int, int]], start: int, end: int
) -> str:
    """``text[start:end]`` z indeksem górnym zapisanym jako ``^x``."""
    if not any(s < end and e > start for s, e in superscript_ranges):
        return text[start:end]
    flags = superscript_mask(len(text), superscript_ranges, start, end)
    return "".join(
        f"^{char}" if flags[i] else char for i, char in enumerate(text[start:end])
    )


def superscript_mask(
    length: int, ranges: Iterable[tuple[int, int]], start: int, end: int
) -> list[bool]:
    """Znaczniki indeksu górnego dla znaków ``[start, end)``."""
    flags = [False] * (end - start)
    for range_start, range_end in ranges:
        for index in range(max(range_start, start), min(range_end, end, length)):
            flags[index - start] = True
    return flags


def make_hit(
    project: CorpusProject,
    start: int,
    end: int,
    spans: Sequence[tuple[int, int]] | None = None,
) -> Hit:
    """Trafienie z kontekstem, mówcą i czasem dla zakresu tekstu projektu.

    ``spans`` to akapity tekstu (:func:`paragraph_spans`) - przy wielu
    trafieniach w jednym projekcie warto policzyć je raz.
    """
    state = project.state
    text = state.text
    if spans is None:
        spans = paragraph_spans(text)
    index = max(bisect_right(spans, (start, len(text) + 1)) - 1, 0)
    para_start, para_end = spans[index]
    left_start = max(para_start, start - CONTEXT_CHARS)
    right_end = min(para_end, end + CONTEXT_CHARS)
    ranges = state.superscript_ranges
    left = marked_text(text, ranges, left_start, start)
    right = marked_text(text, ranges, end, right_end)
    if left_start > para_start:
        left = ELLIPSIS + left
    if right_end < para_end:
        right = right + ELLIPSIS
    return Hit(
        project=project,
        start=start,
        end=end,
        left=left.replace("\n", " "),
        match=marked_text(text, ranges, start, end).replace("\n", " "),
        right=right.replace("\n", " "),
        speaker=state.paragraph_speakers.get(index, ""),
        time_ms=time_span(state.anchors, start, end),
    )


def informant_ranges(project: CorpusProject) -> list[tuple[int, int]]:
    state = project.state
    return informant_spans(state.text, state.paragraph_speakers, state.speakers)


def concordance(
    projects: Iterable[CorpusProject],
    pattern: regex.Pattern[str],
    informant_only: bool = False,
    limit: int = MAX_HITS,
) -> Concordance:
    """Trafienia wzorca w projektach, w kolejności projektów i tekstu.

    ``informant_only`` zostawia trafienia w akapitach informatorów.
    Wzorzec zbyt kosztowny dla któregoś projektu - ``SearchError``.
    """
    hits: list[Hit] = []
    for project in projects:
        matches = find_all(project.state.text, pattern)
        if informant_only:
            matches = restrict_to(matches, informant_ranges(project))
        spans = paragraph_spans(project.state.text) if matches else []
        for start, end in matches:
            if len(hits) == limit:
                return Concordance(tuple(hits), truncated=True)
            hits.append(make_hit(project, start, end, spans))
    return Concordance(tuple(hits))
