"""Testy walidatora reguł VAL-01 do VAL-05 oraz kontraktu document -> notation."""

import pytest

from transkryptor.document.model import Document
from transkryptor.notation.ellipsis import EllipsisStyle
from transkryptor.notation.validator import (
    DEFAULT_ENABLED,
    SEVERITY_HINT,
    enabled_codes,
    validate,
)


def codes(text: str) -> list[str]:
    return [warning.code for warning in validate(text)]


class TestPauseRule:
    """VAL-01 i VAL-04 z acceptance.md i transcription-rules.md."""

    def test_acc04_cut_off_words_are_not_reported(self) -> None:
        """ACC-04: `jeż... kam... kamionka` - brak błędu pauzy."""
        assert validate("jeż... kam... kamionka") == []

    def test_acc05_missing_space_after_pause(self) -> None:
        """ACC-05: `rzeczy ...bo` - ostrzeżenie VAL-01."""
        warnings = validate("rzeczy ...bo")
        assert [warning.code for warning in warnings] == ["VAL-01"]
        warning = warnings[0]
        assert (warning.start, warning.end) == (7, 10)
        assert warning.message

    def test_correct_pause_passes(self) -> None:
        assert validate("takich rzeczy ... bo") == []

    def test_pause_at_text_end_passes(self) -> None:
        assert validate("takich rzeczy ...") == []

    def test_ellipsis_at_text_start_passes(self) -> None:
        assert validate("... początek") == []
        assert validate("...początek") == []

    def test_multiple_bad_pauses_are_all_reported(self) -> None:
        assert codes("a ...b ...c") == ["VAL-01", "VAL-01"]


class TestUnicodeEllipsis:
    """ACC-23: `…` działa w VAL-01 i VAL-04 tak samo jak `...`."""

    def test_acc23_cut_off_words_with_unicode_ellipsis(self) -> None:
        assert validate("jeż… kam… kamionka") == []

    def test_acc23_missing_space_after_unicode_pause(self) -> None:
        warnings = validate("rzeczy …bo")
        assert [w.code for w in warnings] == ["VAL-01"]
        assert (warnings[0].start, warnings[0].end) == (7, 8)
        assert "`…`" in warnings[0].message

    def test_unicode_pause_passes(self) -> None:
        assert validate("takich rzeczy … bo") == []

    def test_omitted_marker_is_not_a_pause(self) -> None:
        assert validate("odstraszy […?] inne") == []


class TestEllipsisStyleHint:
    """VAL-05: wielokropek w zapisie innym niż wybrany (wskazówka)."""

    def test_no_hint_without_style(self) -> None:
        assert validate("rzeczy ... bo i… tak") == []

    def test_foreign_ascii_reported_for_unicode_style(self) -> None:
        warnings = validate("rzeczy ... bo i… tak", EllipsisStyle.UNICODE)
        assert [(w.code, w.start, w.end) for w in warnings] == [("VAL-05", 7, 10)]
        assert warnings[0].severity == SEVERITY_HINT

    def test_foreign_unicode_reported_for_ascii_style(self) -> None:
        warnings = validate("rzeczy ... bo i… tak", EllipsisStyle.ASCII)
        assert [(w.code, w.start, w.end) for w in warnings] == [("VAL-05", 15, 16)]

    def test_fixed_markers_are_not_hinted(self) -> None:
        text = "trzea [...] i […?] tak"
        assert validate(text, EllipsisStyle.UNICODE) == []
        assert validate(text, EllipsisStyle.ASCII) == []


class TestAsideRule:
    """VAL-02: niedomknięty dopisek."""

    def test_acc06_unclosed_aside(self) -> None:
        """ACC-06: `trzea [świnię` - ostrzeżenie VAL-02."""
        warnings = validate("trzea [świnię")
        assert [warning.code for warning in warnings] == ["VAL-02"]
        assert warnings[0].start == 6
        assert warnings[0].end == len("trzea [świnię")

    def test_closed_aside_passes(self) -> None:
        assert validate("trzea [świnię] rościońdź") == []

    def test_ascii_ellipsis_aside_is_only_val02(self) -> None:
        """`[...` to dopisek z kropkami ASCII - bez VAL-03."""
        assert codes("tekst [...") == ["VAL-02"]


class TestOmittedRule:
    """VAL-03: marker pominiętego tekstu inny niż `[…?]`."""

    def test_acc07_wrong_omitted_marker(self) -> None:
        """ACC-07: `odstraszy […] inne ptaki` - ostrzeżenie VAL-03."""
        warnings = validate("odstraszy […] inne ptaki")
        assert [warning.code for warning in warnings] == ["VAL-03"]
        warning = warnings[0]
        assert warning.start == 10
        assert warning.message

    def test_correct_omitted_marker_passes(self) -> None:
        assert validate("odstraszy […?] inne ptaki") == []

    def test_unclosed_malformed_marker_reports_val02_and_val03(self) -> None:
        assert codes("tekst […? i dalej") == ["VAL-02", "VAL-03"]


class TestSyntheticExamples:
    """Przykłady syntetyczne ze specyfikacja.md bez błędów strukturalnych."""

    @pytest.mark.parametrize(
        "text",
        [
            "kiedyź jag nie było jeszcze tych ... nowyczesnych tyh maszyn",
            "zamudze (!) pani kupe czasu ale to nic ...",
            "zaź jeszcze docioł czy doł mocniej nogie (?) dogioł ...",
            "bo tyn to tylko odstraszy […?] inne ptaki ...",
            "no trzea [świnię] ... rościońdź i jelita w… wy… wywalić ...",
            "jeżeli jest wypalane ... to na przykład jeż... kam... kamionka",
            "wiedziaam wyczytaam obhakaam",
            "zmar-zły ta-ak",
            "uóna sóm słóńce",
        ],
    )
    def test_examples_pass_validation(self, text: str) -> None:
        assert validate(text) == []


class TestContract:
    """Kontrakt `document -> notation`: tekst wejściowy, ostrzeżenia wyjściowe."""

    def test_validate_accepts_document_text(self) -> None:
        doc = Document(text="rzeczy ...bo [świnię")
        warnings = validate(doc.text)
        assert [warning.code for warning in warnings] == ["VAL-01", "VAL-02"]

    def test_validate_does_not_mutate_document(self) -> None:
        doc = Document(text="rzeczy ...bo")
        revision_before = doc.revision
        validate(doc.text)
        assert doc.text == "rzeczy ...bo"
        assert doc.revision == revision_before

    def test_warnings_carry_code_range_and_message(self) -> None:
        for warning in validate("rzeczy ...bo […] tekst [x"):
            assert warning.code
            assert 0 <= warning.start < warning.end
            assert warning.message


class TestExtendedRules:
    """VAL-06…VAL-11 (faza 10, propozycja 13)."""

    def test_val06_marker_touching_next_word(self) -> None:
        warnings = validate("nogie (?)dogioł i (!) pani")
        assert [(w.code, w.start, w.end) for w in warnings] == [("VAL-06", 6, 9)]

    def test_val06_marker_followed_by_space_or_end_passes(self) -> None:
        assert validate("zamudze (!) pani (?)") == []

    def test_val07_double_space_is_a_hint(self) -> None:
        (warning,) = validate("a   b")
        assert (warning.code, warning.start, warning.end) == ("VAL-07", 1, 4)
        assert warning.severity == SEVERITY_HINT

    def test_val08_space_before_closing_bracket(self) -> None:
        (warning,) = validate("trzea [świnię ]")
        assert (warning.code, warning.start, warning.end) == ("VAL-08", 13, 15)
        assert warning.severity == SEVERITY_HINT

    def test_val09_nested_aside(self) -> None:
        warnings = [w for w in validate("[a [b] c]") if w.code == "VAL-09"]
        assert [(w.start, w.end) for w in warnings] == [(3, 6)]

    def test_val09_omission_marker_inside_aside_is_not_nesting(self) -> None:
        assert validate("[trzea […?] coś]") == []

    def test_val10_superscript_on_other_letter(self) -> None:
        warnings = validate("soma", superscript_ranges=[(2, 4)])
        assert [(w.code, w.start, w.end) for w in warnings] == [("VAL-10", 3, 4)]
        assert "`a`" in warnings[0].message

    def test_val10_allowed_letters_pass(self) -> None:
        assert validate("som uod", superscript_ranges=[(2, 3), (4, 5)]) == []

    def test_val11_is_disabled_by_default(self) -> None:
        assert validate("som") == []

    def test_val11_hint_when_enabled(self) -> None:
        warnings = validate("som uod ona", enabled={"VAL-11"})
        assert [(w.code, w.start) for w in warnings] == [
            ("VAL-11", 2),
            ("VAL-11", 4),
        ]
        assert all(w.severity == SEVERITY_HINT for w in warnings)

    def test_val11_skips_superscript_letters(self) -> None:
        assert validate("som", superscript_ranges=[(2, 3)], enabled={"VAL-11"}) == []

    def test_acc39_text_reports_every_problem(self) -> None:
        """ACC-39: `[ [dopisek] ]`, `(?)słowo` i indeks górny na `a`."""
        text = "[ [dopisek] ] (?)słowo ta"
        codes = {w.code for w in validate(text, superscript_ranges=[(24, 25)])}
        assert {"VAL-06", "VAL-08", "VAL-09", "VAL-10"} <= codes

    def test_disabled_rule_is_not_reported(self) -> None:
        assert validate("a  b", enabled=set()) == []
        assert validate("trzea [świnię", enabled={"VAL-01"}) == []


def test_enabled_codes_apply_overrides() -> None:
    enabled = enabled_codes({"VAL-07": False, "VAL-11": True})
    assert "VAL-07" not in enabled
    assert "VAL-11" in enabled
    assert enabled - {"VAL-11"} == DEFAULT_ENABLED - {"VAL-07"}
