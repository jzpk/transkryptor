"""Reguły fonetyczne jako dane: ładowanie, walidacja, zapis i limit czasu."""

import time

import pytest

from transkryptor.notation.rules import (
    USER_PREFIX,
    PhoneticRule,
    builtin_codes,
    builtin_rules,
    check_rule,
    dumps_rules,
    parse_rules,
    parse_template,
)
from transkryptor.notation.suggestions import (
    default_rules,
    propose,
    propose_with_report,
    without_overlaps,
)

ORIGINAL_CODES = (
    "SUG-NAS-A-FINAL",
    "SUG-NAS-E-DENT",
    "SUG-NAS-E-LAB",
    "SUG-NAS-A-LAB",
    "SUG-LAB-U-INIT",
)


def user_rule(**overrides) -> str:
    fields = {
        "code": '"USR-TEST"',
        "label": '"Test"',
        "pattern": "'ą$'",
        "replacement": "'o^m'",
        "confidence": "0.4",
    }
    fields.update(overrides)
    body = "\n".join(f"{k} = {v}" for k, v in fields.items() if v is not None)
    return f"[[rule]]\n{body}\n"


def _old_rules(word: str) -> list[tuple[str, int, int, str, tuple]]:
    """Reguły z wersji 0.4.0 (kod Pythona) - wzorzec dla testu równoważności."""
    edits = []
    if len(word) > 1 and word.endswith("ą"):
        edits.append(("SUG-NAS-A-FINAL", len(word) - 1, len(word), "om", ((1, 2),)))
    for i in range(len(word) - 1):
        if word[i] == "ę" and word[i + 1] in "dtscz":
            edits.append(("SUG-NAS-E-DENT", i, i + 1, "en", ((1, 2),)))
        if word[i] == "ę" and word[i + 1] in "pb":
            edits.append(("SUG-NAS-E-LAB", i, i + 1, "em", ((1, 2),)))
        if word[i] == "ą" and word[i + 1] in "pb":
            edits.append(("SUG-NAS-A-LAB", i, i + 1, "om", ((1, 2),)))
    if len(word) > 1 and word.startswith("o"):
        edits.append(("SUG-LAB-U-INIT", 0, 1, "uo", ((0, 1),)))
    return edits


class TestBuiltinRules:
    def test_builtin_file_loads_without_errors(self) -> None:
        loaded = builtin_rules()
        assert loaded.errors == ()
        assert {rule.code for rule in loaded.rules} >= set(ORIGINAL_CODES)
        assert all(rule.builtin for rule in loaded.rules)
        assert not any(code.startswith(USER_PREFIX) for code in builtin_codes())

    def test_same_results_as_python_rules(self) -> None:
        """Bramka fazy 10: przeniesienie do danych nie zmienia wyników."""
        words = (
            "są będzie zęby ząb od oko o ą ę kąpie dębowy mąka wąs pięć"
            " ostatnią obsłużą odbędą tęskniąc gęś pąk sąsiedzi ośm Są Od"
        )
        originals = [r for r in default_rules() if r.code in ORIGINAL_CODES]
        new = {
            (s.code, s.start, s.end, s.replacement, s.superscript_ranges)
            for s in propose(words, originals)
        }
        old = set()
        position = 0
        for word in words.split(" "):
            for code, start, end, replacement, ranges in _old_rules(word):
                old.add((code, position + start, position + end, replacement, ranges))
            position += len(word) + 1
        assert new == old

    @pytest.mark.parametrize(
        ("text", "code", "expected"),
        [
            ("wiedziałam", "SUG-L-INTERVOC", "wiedziaam"),
            ("kiedyś jak", "SUG-VOICE-S-PAIR", "kiedyź jak"),
            ("jak nowy", "SUG-VOICE-K-PAIR", "jag nowy"),
            ("tych", "SUG-CH-FINAL", "tyh"),
            ("są", "SUG-A-O-ACUTE", "sóm"),
            ("kosa", "SUG-LAB-MEDIAL", "kuosa"),
        ],
    )
    def test_new_rules_follow_specification_examples(
        self, text, code, expected
    ) -> None:
        (suggestion,) = [s for s in propose(text) if s.code == code]
        result = (
            text[: suggestion.start] + suggestion.replacement + text[suggestion.end :]
        )
        assert result == expected

    def test_new_rules_are_not_applied_automatically(self) -> None:
        new = [r for r in default_rules() if r.code not in ORIGINAL_CODES]
        assert new and not any(rule.auto_apply for rule in new)

    def test_pair_rule_needs_whitespace_between_words(self) -> None:
        assert [s for s in propose("kiedyś, jak") if s.code == "SUG-VOICE-S-PAIR"] == []
        assert [s for s in propose("kiedyś bo") if s.code == "SUG-VOICE-S-PAIR"] == []

    def test_preferred_rules_win_overlaps(self) -> None:
        suggestions = propose("są")
        (default_pick,) = without_overlaps(suggestions)
        assert default_pick.code == "SUG-NAS-A-FINAL"
        (preferred,) = without_overlaps(suggestions, preferred={"SUG-A-O-ACUTE"})
        assert preferred.code == "SUG-A-O-ACUTE"


class TestUserRules:
    def test_valid_user_rule(self) -> None:
        loaded = parse_rules(user_rule(), "user.toml")
        assert loaded.errors == ()
        (rule,) = loaded.rules
        assert rule.code == "USR-TEST" and rule.label_text == "Test"
        assert not rule.builtin and not rule.auto_apply
        (suggestion,) = propose("są", loaded.rules)
        assert suggestion.replacement == "om"
        assert suggestion.superscript_ranges == ((1, 2),)

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"code": '"SUG-X"'}, "code"),
            ({"code": '"usr-x"'}, "code"),
            ({"label": None}, "label"),
            ({"pattern": "'(ą'"}, "pattern"),
            ({"pattern": "'" + "a" * 201 + "'"}, "pattern"),
            ({"replacement": "'o^'"}, "replacement"),
            ({"replacement": "'\\2'"}, "replacement"),
            ({"replacement": "''"}, "replacement"),
            ({"confidence": "0"}, "confidence"),
            ({"confidence": "1.5"}, "confidence"),
            ({"scope": '"sentence"'}, "scope"),
        ],
    )
    def test_invalid_rule_is_skipped_with_location(self, overrides, field) -> None:
        raw = user_rule(code='"USR-OK"') + "\n" + user_rule(**overrides)
        loaded = parse_rules(raw, "user.toml")
        assert [rule.code for rule in loaded.rules] == ["USR-OK"]
        (error,) = loaded.errors
        assert (error.source, error.index, error.field) == ("user.toml", 2, field)
        assert "user.toml" in error.message and "2" in error.message

    def test_duplicate_and_reserved_codes(self) -> None:
        raw = user_rule() + user_rule()
        loaded = parse_rules(raw, "user.toml")
        assert len(loaded.rules) == 1 and loaded.errors[0].field == "code"
        taken = parse_rules(user_rule(), "u.toml", taken_codes={"USR-TEST"})
        assert taken.rules == () and taken.errors[0].field == "code"

    def test_broken_toml_is_one_error(self) -> None:
        loaded = parse_rules("[[rule]\ncode =", "user.toml")
        assert loaded.rules == () and loaded.errors[0].field == "toml"

    def test_round_trip_through_toml(self) -> None:
        rule = PhoneticRule(
            code="USR-ESC",
            label={"*": 'Cudzysłów " i \\ ukośnik'},
            pattern=r'([aeo])ł(?=\s+"x")',
            replacement=r"\1^u\^",
            confidence=0.25,
            scope="pair",
            description={"pl": "opis", "en": "description"},
            example="ała x",
            auto_apply=True,
        )
        loaded = parse_rules(dumps_rules([rule]), "export.toml")
        assert loaded.errors == ()
        assert loaded.rules == (rule,)

    def test_check_rule_reports_problem_for_editor(self) -> None:
        good = parse_rules(user_rule(), "u.toml").rules[0]
        assert check_rule(good) is None
        bad = PhoneticRule("USR-X", {"*": "x"}, "(", "a", 0.3)
        assert "pattern" in (check_rule(bad) or "")
        assert check_rule(good, taken_codes={"USR-TEST"}) is not None


class TestTemplate:
    def test_groups_superscripts_and_escapes(self) -> None:
        import regex

        match = regex.search("(a)(b)", "ab")
        text, ranges = parse_template(r"\2^m^n\^\\\1").expand(match)
        assert text == "bmn^\\a"
        assert ranges == ((1, 3),)


class TestCatastrophicBacktracking:
    def test_slow_pattern_is_interrupted_and_reported(self) -> None:
        """ACC-42: wolny wzorzec nie blokuje - reguła przerwana, reszta działa."""
        slow = parse_rules(
            user_rule(code='"USR-SLOW"', pattern="'(a|aa)+$'", replacement="'x'"),
            "u.toml",
        ).rules
        rules = [*slow, *default_rules()]
        text = ("a" * 40 + "b ") * 50 + "są"
        started = time.monotonic()
        report = propose_with_report(text, rules)
        assert time.monotonic() - started < 2
        assert report.failed == ("USR-SLOW",)
        assert any(s.code == "SUG-NAS-A-FINAL" for s in report.suggestions)
        assert not any(s.code == "USR-SLOW" for s in report.suggestions)
