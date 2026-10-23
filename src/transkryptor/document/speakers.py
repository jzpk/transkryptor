"""Mówcy wypowiedzi i akapity dokumentu (bez Qt).

Tekst dokumentu pozostaje ciągły — akapity rozdziela znak nowej linii.
Mówca jest własnością akapitu: ``Document.paragraph_speakers`` przypisuje
indeksowi akapitu klucz mówcy z listy ``Document.speakers``. Klucz (``B``,
``I``, ``I2``…) to etykieta widoczna w edytorze i eksporcie (``B:``),
a ``label`` — opis w metryczce (np. „Badacz”, kod informatora).

Etykiety mówców o roli informatora są pomijane w eksporcie anonimizowanym
(klucz zostaje).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from transkryptor.i18n import all_translations, tr

RESEARCHER = "researcher"
INFORMANT = "informant"
OTHER = "other"
ROLES = (RESEARCHER, INFORMANT, OTHER)

KEY_MAX_LENGTH = 8
_KEY_RE = re.compile(rf"^\w{{1,{KEY_MAX_LENGTH}}}$")


@dataclass(frozen=True)
class Speaker:
    key: str
    label: str = ""
    role: str = OTHER

    @property
    def is_informant(self) -> bool:
        return self.role == INFORMANT

    @property
    def description(self) -> str:
        """Opis do legendy: etykieta albo nazwa roli."""
        return self.label or role_label(self.role)


DEFAULT_SPEAKERS: tuple[Speaker, ...] = (
    Speaker("B", "", RESEARCHER),
    Speaker("I", "", INFORMANT),
)


def role_label(role: str) -> str:
    return tr(f"speakers.role.{role}")


def is_valid_key(key: str) -> bool:
    """Klucz: 1–8 liter lub cyfr (bez spacji i dwukropka)."""
    return bool(_KEY_RE.match(key))


def check_speakers(speakers: Iterable[Speaker]) -> None:
    """``ValueError`` przy błędnym kluczu, roli albo powtórzonym kluczu."""
    seen: set[str] = set()
    for speaker in speakers:
        if not is_valid_key(speaker.key):
            raise ValueError(f"nieprawidłowy klucz mówcy: {speaker.key!r}")
        if speaker.role not in ROLES:
            raise ValueError(f"nieznana rola mówcy: {speaker.role!r}")
        if speaker.key in seen:
            raise ValueError(f"powtórzony klucz mówcy: {speaker.key!r}")
        seen.add(speaker.key)


def guess_role(key: str) -> str:
    """Rola z klucza (import): ``B`` — badacz, ``I…`` — informator."""
    upper = key.upper()
    if upper.startswith("B"):
        return RESEARCHER
    if upper.startswith("I"):
        return INFORMANT
    return OTHER


def speakers_for_clusters(
    existing: Iterable[Speaker], count: int
) -> tuple[tuple[Speaker, ...], list[str]]:
    """Mówcy dla ``count`` głosów z podziału na mówców i klucz każdego głosu.

    Głosy (numerowane w kolejności pojawiania się) dostają kolejnych mówców
    z listy dokumentu — domyślnie pierwszy ``B``, drugi ``I``. Gdy głosów
    jest więcej, lista jest uzupełniana informatorami ``I2``, ``I3``…
    Pusta lista oznacza mówców domyślnych.
    """
    speakers = list(existing) or list(DEFAULT_SPEAKERS)
    keys = {speaker.key for speaker in speakers}
    number = 2
    while len(speakers) < count:
        key = f"I{number}"
        number += 1
        if key in keys:
            continue
        keys.add(key)
        speakers.append(Speaker(key, "", INFORMANT))
    return tuple(speakers), [speaker.key for speaker in speakers[:count]]


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Zakresy ``(start, end)`` akapitów (bez znaku nowej linii)."""
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        end = text.find("\n", start)
        if end < 0:
            spans.append((start, len(text)))
            return spans
        spans.append((start, end))
        start = end + 1


def paragraph_count(text: str) -> int:
    return text.count("\n") + 1


def clean_assignments(
    assignments: Mapping[int, str], text: str, speakers: Iterable[Speaker]
) -> dict[int, str]:
    """Przypisania z indeksami w tekście i kluczami z listy mówców."""
    keys = {speaker.key for speaker in speakers}
    count = paragraph_count(text)
    return {
        index: key
        for index, key in sorted(assignments.items())
        if 0 <= index < count and key in keys
    }


def shift_assignments(
    assignments: Mapping[int, str], removed: str, inserted: str, first: int
) -> dict[int, str]:
    """Przypisania po zastąpieniu tekstu zaczynającego się w akapicie ``first``.

    Usunięte znaki nowej linii scalają akapity z pierwszym (zostaje jego
    mówca), wstawione dzielą akapit — nowe akapity są bez mówcy.
    """
    removed_lines = removed.count("\n")
    delta = inserted.count("\n") - removed_lines
    result: dict[int, str] = {}
    for index, key in assignments.items():
        if index <= first:
            result[index] = key
        elif index > first + removed_lines:
            result[index + delta] = key
    return result


def informant_spans(
    text: str, assignments: Mapping[int, str], speakers: Iterable[Speaker]
) -> list[tuple[int, int]]:
    """Zakresy akapitów przypisanych mówcom o roli informatora."""
    informants = {speaker.key for speaker in speakers if speaker.is_informant}
    return [
        span
        for index, span in enumerate(paragraph_spans(text))
        if assignments.get(index) in informants
    ]


def legend(speakers: Iterable[Speaker], anonymize: bool = False) -> str:
    """Legenda mówców do metryczki: ``B — Badacz; I — Informator``."""
    parts: list[str] = []
    for speaker in speakers:
        description = (
            role_label(speaker.role)
            if anonymize and speaker.is_informant
            else speaker.description
        )
        parts.append(f"{speaker.key} — {description}")
    return "; ".join(parts)


_LEGEND_ITEM_RE = re.compile(r"^\s*(\w{1,8})\s*[—–-]\s*(.*?)\s*$")


def parse_legend(value: str) -> list[Speaker]:
    """Odwrotność :func:`legend` (import DOCX); błędne pozycje są pomijane."""
    speakers: list[Speaker] = []
    seen: set[str] = set()
    # Opis równy nazwie roli (w dowolnym języku) to mówca bez własnej etykiety.
    roles = {
        name.casefold(): role
        for role in ROLES
        for name in all_translations(f"speakers.role.{role}")
    }
    for item in value.split(";"):
        match = _LEGEND_ITEM_RE.match(item)
        if match is None or match[1] in seen:
            continue
        key, description = match[1], match[2]
        role = roles.get(description.casefold())
        label = "" if role is not None else description
        seen.add(key)
        speakers.append(Speaker(key, label, role or guess_role(key)))
    return speakers
