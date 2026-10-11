"""Regułowe kandydaty zapisu fonetycznego dla tekstu ortograficznego.

Realizuje „Reguły ASR” z ``specs/transcription-rules.md``: silnik generuje
kandydatów dla znanych zjawisk z informacją o źródle i pewności. Kandydaci
są wyłącznie propozycjami — funkcja jest czysta, nie mutuje dokumentu.
Zastosowanie wykonuje UI: automatycznie tylko dla reguł wybranych przez
użytkownika (REQ-15), pozostałe na jego żądanie (ACC-12).

Reguły są danymi (``notation.rules``): wbudowane w pakiet i własne reguły
użytkownika. Wzorzec może pochodzić od użytkownika, więc każde dopasowanie
ma limit czasu — reguła, która go przekroczy (katastrofalne nawracanie),
jest pomijana do końca przebiegu i zgłaszana w ``Proposal.failed``. Brak
korpusu referencyjnego oznacza, że pewność jest orientacyjna, a ekspert
zawsze decyduje o zastosowaniu.
"""

from __future__ import annotations

import re
import time
from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from transkryptor.notation.rules import (
    SCOPE_PAIR,
    CompiledRule,
    PhoneticRule,
    builtin_rules,
    compile_rule,
)

_WORD_RE = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+")

# Limit jednego dopasowania (słowo lub para słów) i łączny limit reguły
# w jednym przebiegu — zwykły wzorzec mieści się w nich wielokrotnie.
MATCH_TIMEOUT_S = 0.05
RULE_BUDGET_S = 2.0


@dataclass(frozen=True)
class Suggestion:
    """Propozycja zapisu fonetycznego dla fragmentu tekstu źródłowego.

    ``superscript_ranges`` to półotwarte zakresy względem ``replacement``,
    które po zastosowaniu powinny otrzymać format indeksu górnego
    (nosowość ``m``/``n``, labializacja ``u``). ``word`` i ``word_start``
    opisują słowo źródłowe (dla reguł par — oba słowa) — kontekst do
    prezentacji propozycji.
    """

    code: str
    start: int
    end: int
    original: str
    replacement: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    source: str = "rule"
    confidence: float = 0.0
    message: str = ""
    word: str = ""
    word_start: int = 0


@dataclass(frozen=True)
class RuleInfo:
    """Opis reguły dla UI: wybór reguł stosowanych automatycznie (REQ-15)."""

    code: str
    label: str
    confidence: float
    auto_apply: bool = False


@dataclass(frozen=True)
class Proposal:
    """Kandydaci i kody reguł przerwanych limitem czasu."""

    suggestions: list[Suggestion]
    failed: tuple[str, ...] = ()


def rule_infos(rules: Iterable[PhoneticRule]) -> tuple[RuleInfo, ...]:
    return tuple(
        RuleInfo(rule.code, rule.label_text, rule.confidence, rule.auto_apply)
        for rule in rules
    )


def default_rules() -> tuple[PhoneticRule, ...]:
    """Reguły wbudowane — zestaw używany, gdy wywołujący nie poda własnego."""
    return builtin_rules().rules


def propose(
    text: str,
    rules: Iterable[PhoneticRule] | None = None,
    *,
    timeout_s: float = MATCH_TIMEOUT_S,
) -> list[Suggestion]:
    """Zwraca regułowych kandydatów zapisu fonetycznego dla tekstu.

    Wejściem jest zwykle hipoteza ortograficzna ASR. Wynik jest posortowany
    po pozycji i nigdy nie modyfikuje wejścia.
    """
    return propose_with_report(text, rules, timeout_s=timeout_s).suggestions


def propose_with_report(
    text: str,
    rules: Iterable[PhoneticRule] | None = None,
    *,
    timeout_s: float = MATCH_TIMEOUT_S,
    budget_s: float = RULE_BUDGET_S,
) -> Proposal:
    """Jak :func:`propose`, ale zgłasza reguły przerwane limitem czasu."""
    compiled = [
        compile_rule(rule) for rule in (default_rules() if rules is None else rules)
    ]
    words = list(_WORD_RE.finditer(text))
    suggestions: list[Suggestion] = []
    failed: list[str] = []
    for rule in compiled:
        deadline = time.monotonic() + budget_s
        try:
            for fragment, base, first_len in _fragments(text, words, rule):
                remaining = min(timeout_s, deadline - time.monotonic())
                if remaining <= 0:
                    raise TimeoutError
                suggestions += _match(rule, fragment, base, first_len, remaining)
        except TimeoutError:
            failed.append(rule.rule.code)
            suggestions = [s for s in suggestions if s.code != rule.rule.code]
    return Proposal(sorted(suggestions, key=lambda s: (s.start, s.code)), tuple(failed))


def _fragments(
    text: str, words: list[Any], rule: CompiledRule
) -> Iterator[tuple[str, int, int]]:
    """Fragmenty do dopasowania: ``(tekst, początek, długość pierwszego słowa)``.

    Dla reguł par to dwa sąsiednie słowa rozdzielone samymi odstępami;
    dopasowanie musi zaczynać się w pierwszym, więc nie powtarza się.
    """
    if rule.rule.scope != SCOPE_PAIR:
        for word in words:
            yield word.group(0), word.start(), len(word.group(0))
        return
    for first, second in zip(words, words[1:], strict=False):
        gap = text[first.end() : second.start()]
        if gap.isspace():
            yield (
                text[first.start() : second.end()],
                first.start(),
                first.end() - first.start(),
            )


def _match(
    rule: CompiledRule, fragment: str, base: int, first_len: int, timeout: float
) -> list[Suggestion]:
    found: list[Suggestion] = []
    for match in rule.regex.finditer(fragment, timeout=timeout):
        start, end = match.span()
        if start == end or start >= first_len:
            continue  # puste dopasowanie albo całe w drugim słowie pary
        replacement, ranges = rule.template.expand(match)
        found.append(
            Suggestion(
                code=rule.rule.code,
                start=base + start,
                end=base + end,
                original=fragment[start:end],
                replacement=replacement,
                superscript_ranges=ranges,
                confidence=rule.rule.confidence,
                message=rule.rule.description_text,
                word=fragment,
                word_start=base,
            )
        )
    return found


def without_overlaps(
    suggestions: list[Suggestion], preferred: Collection[str] = ()
) -> list[Suggestion]:
    """Usuwa kandydatów nachodzących na siebie, zostawiając pewniejszych.

    Automatyczne stosowanie kilku zamian na tym samym fragmencie
    zniszczyłoby tekst, więc z każdej grupy kolizji zostaje jedna
    propozycja: najpierw z reguł ``preferred`` (wybranych do automatycznego
    stosowania), potem wyższa pewność, przy remisie — wcześniejsza pozycja.
    Wynik jest posortowany po pozycji.
    """
    kept: list[Suggestion] = []
    ordered = sorted(
        suggestions, key=lambda s: (s.code not in preferred, -s.confidence, s.start)
    )
    for candidate in ordered:
        if all(candidate.end <= s.start or s.end <= candidate.start for s in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda s: (s.start, s.code))


__all__ = [
    "Proposal",
    "RuleInfo",
    "Suggestion",
    "default_rules",
    "propose",
    "propose_with_report",
    "rule_infos",
    "without_overlaps",
]
