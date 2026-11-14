"""Regiony i gwary: zestawy reguł fonetycznych do wyboru (zgłoszenie #49).

Region (``notation/data/regions.toml``) to nazwa i kody reguł wbudowanych
typowych dla gwar regionu, np. mazurzenie na Mazowszu albo udźwięczniająca
fonetyka międzywyrazowa w Wielkopolsce. Wybór regionu w panelu ASR
zaznacza reguły domyślne i reguły regionu (:func:`region_selection`);
dalej transkrybent decyduje sam. Pusty klucz (:data:`NO_REGION`) to brak
regionu - same reguły domyślne.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources

from transkryptor.notation.rules import localized
from transkryptor.notation.suggestions import RuleInfo

NO_REGION = ""
REGIONS_SOURCE = "regions.toml"


@dataclass(frozen=True)
class Region:
    """Region: klucz, teksty w językach interfejsu i kody reguł."""

    key: str
    label: Mapping[str, str]
    description: Mapping[str, str]
    rules: tuple[str, ...]

    @property
    def label_text(self) -> str:
        return localized(self.label)

    @property
    def description_text(self) -> str:
        return localized(self.description)


@cache
def builtin_regions() -> tuple[Region, ...]:
    """Regiony wbudowane w pakiet (wczytywane raz)."""
    raw = (
        resources.files("transkryptor.notation")
        .joinpath("data", REGIONS_SOURCE)
        .read_text(encoding="utf-8")
    )
    return tuple(
        Region(
            key=entry["key"],
            label=dict(entry["label"]),
            description=dict(entry.get("description", {})),
            rules=tuple(entry.get("rules", ())),
        )
        for entry in tomllib.loads(raw).get("region", [])
    )


def region_keys() -> tuple[str, ...]:
    """Dopuszczalne klucze regionu (z pustym - brak regionu)."""
    return (NO_REGION, *(region.key for region in builtin_regions()))


def region_by_key(key: str) -> Region | None:
    """Region o kluczu; None dla braku regionu i nieznanego klucza."""
    return next((region for region in builtin_regions() if region.key == key), None)


def region_selection(key: str, rules: Iterable[RuleInfo]) -> frozenset[str]:
    """Reguły zaznaczone dla regionu: domyślne i reguły regionu.

    Kody regionu spoza ``rules`` (np. reguła usunięta) są pomijane.
    """
    rules = tuple(rules)
    region = region_by_key(key)
    extra = set(region.rules) if region is not None else set()
    return frozenset(
        rule.code for rule in rules if rule.auto_apply or rule.code in extra
    )


__all__ = [
    "NO_REGION",
    "Region",
    "builtin_regions",
    "region_by_key",
    "region_keys",
    "region_selection",
]
