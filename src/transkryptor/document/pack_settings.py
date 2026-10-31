"""Ustawienia z paczki do przekazania: przyjęcie, scalenie albo pominięcie (bez Qt).

Odbiorca paczki (``document/pack.py``) decyduje osobno o regułach
fonetycznych, wstawkach i ustawieniach notacji (zapis wielokropka i reguły
walidatora):

- ``ACCEPT`` - ustawienia z paczki zastępują własne;
- ``MERGE`` - własne zostają, a z paczki dochodzi to, czego brakuje
  (reguły o nowych kodach, wstawki o nowej treści, ustawienia walidatora
  dla reguł bez własnego wyboru; zapis wielokropka zostaje własny);
- ``SKIP`` - paczka nie zmienia ustawień.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from transkryptor.document.pack import PackSettings
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.notation.rules import PhoneticRule, builtin_codes, parse_rules
from transkryptor.settings import (
    Settings,
    decode_bool_map,
    decode_snippets,
    encode_bool_map,
    encode_snippets,
)

ACCEPT = "accept"
MERGE = "merge"
SKIP = "skip"
CHOICES = (ACCEPT, MERGE, SKIP)

RULES = "rules"
SNIPPETS = "snippets"
NOTATION = "notation"


def available_groups(settings: PackSettings) -> list[str]:
    """Grupy ustawień, które paczka zawiera (w kolejności okna)."""
    groups: list[str] = []
    if settings.rules_toml.strip():
        groups.append(RULES)
    if settings.snippets_spec.strip():
        groups.append(SNIPPETS)
    if settings.has_notation:
        groups.append(NOTATION)
    return groups


@dataclass(frozen=True)
class AppliedSettings:
    """Wynik decyzji: nowe ustawienia i reguły (None - reguły bez zmian)."""

    settings: Settings
    user_rules: tuple[PhoneticRule, ...] | None = None


def apply_pack_settings(
    pack: PackSettings,
    choices: dict[str, str],
    settings: Settings,
    user_rules: Sequence[PhoneticRule],
) -> AppliedSettings:
    """Ustawienia po decyzjach ``choices`` (grupa → ``ACCEPT``/``MERGE``/``SKIP``)."""
    rules = _rules(pack.rules_toml, choices.get(RULES, SKIP), tuple(user_rules))
    snippets = _snippets(
        pack.snippets_spec, choices.get(SNIPPETS, SKIP), settings.snippets.spec
    )
    updated = replace(settings, snippets=replace(settings.snippets, spec=snippets))
    updated = _notation(pack, choices.get(NOTATION, SKIP), updated)
    return AppliedSettings(updated, rules if rules != tuple(user_rules) else None)


def _rules(
    raw: str, choice: str, mine: tuple[PhoneticRule, ...]
) -> tuple[PhoneticRule, ...]:
    if choice == SKIP or not raw.strip():
        return mine
    theirs = parse_rules(raw, "rules.toml", taken_codes=builtin_codes()).rules
    if choice == ACCEPT:
        return theirs
    codes = {rule.code for rule in mine}
    return (*mine, *(rule for rule in theirs if rule.code not in codes))


def _snippets(raw: str, choice: str, mine: str) -> str:
    theirs = decode_snippets(raw)
    if choice == SKIP or not theirs:
        return mine
    if choice == ACCEPT:
        return encode_snippets(theirs)
    own = decode_snippets(mine) or ()
    texts = {snippet.text for snippet in own}
    return encode_snippets((*own, *(s for s in theirs if s.text not in texts)))


def _notation(pack: PackSettings, choice: str, settings: Settings) -> Settings:
    if choice == SKIP or not pack.has_notation:
        return settings
    theirs = decode_bool_map(pack.validator_spec) or {}
    if choice == ACCEPT:
        overrides = theirs
        notation = settings.notation
        if pack.ellipsis_style in {style.value for style in EllipsisStyle}:
            notation = replace(notation, ellipsis_style=pack.ellipsis_style)
    else:
        overrides = {**theirs, **settings.validator.overrides}
        notation = settings.notation
    return replace(
        settings,
        notation=notation,
        validator=replace(
            settings.validator, overrides_spec=encode_bool_map(overrides)
        ),
    )
