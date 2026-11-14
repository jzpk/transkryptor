"""Regiony i gwary: zestawy reguł fonetycznych (zgłoszenie #49)."""

import pytest

from transkryptor.notation.regions import (
    NO_REGION,
    builtin_regions,
    region_by_key,
    region_keys,
    region_selection,
)
from transkryptor.notation.rules import builtin_codes
from transkryptor.notation.suggestions import default_rules, propose, rule_infos

DEFAULT_AUTO = frozenset(rule.code for rule in default_rules() if rule.auto_apply)


def test_regions_load_and_reference_existing_rules() -> None:
    regions = builtin_regions()
    assert {"wielkopolska", "gorny-slask", "podhale", "kurpie", "warmia"} <= {
        region.key for region in regions
    }
    for region in regions:
        assert region.label_text and region.description_text
        assert region.rules and set(region.rules) <= builtin_codes()
    assert region_keys()[0] == NO_REGION
    assert len(set(region_keys())) == len(region_keys())


def test_no_region_selects_default_rules() -> None:
    assert region_selection(NO_REGION, rule_infos(default_rules())) == DEFAULT_AUTO
    assert region_selection("nieznany", rule_infos(default_rules())) == DEFAULT_AUTO
    assert region_by_key(NO_REGION) is None


def test_region_adds_its_rules_to_defaults() -> None:
    selection = region_selection("kurpie", rule_infos(default_rules()))
    assert selection >= DEFAULT_AUTO
    assert {"SUG-MAZ-SZ", "SUG-MAZ-CZ", "SUG-MAZ-ZH"} <= selection
    wielkopolska = region_selection("wielkopolska", rule_infos(default_rules()))
    assert "SUG-VOICE-S-PAIR" in wielkopolska
    assert "SUG-MAZ-SZ" not in wielkopolska


def test_region_skips_rules_it_does_not_know() -> None:
    rules = [r for r in rule_infos(default_rules()) if r.code != "SUG-MAZ-SZ"]
    assert "SUG-MAZ-SZ" not in region_selection("kurpie", rules)


@pytest.mark.parametrize(
    ("text", "code", "expected"),
    [
        ("szafa", "SUG-MAZ-SZ", "safa"),
        ("czas", "SUG-MAZ-CZ", "cas"),
        ("żaba", "SUG-MAZ-ZH", "zaba"),
    ],
)
def test_mazurzenie_rules(text, code, expected) -> None:
    (suggestion,) = [s for s in propose(text) if s.code == code]
    assert text[: suggestion.start] + suggestion.replacement + text[
        suggestion.end :
    ] == (expected)


def test_mazurzenie_leaves_rz() -> None:
    assert not [s for s in propose("rzeka") if s.code.startswith("SUG-MAZ")]
