"""Testy regułowych kandydatów zapisu fonetycznego (sugestie, nie mutacje)."""

from transkryptor.notation.suggestions import propose


def by_code(suggestions, code):
    return [s for s in suggestions if s.code == code]


class TestNasalFinalA:
    def test_final_a_ogonek_proposes_superscript_m(self) -> None:
        """Przykład ze specyfikacji: są → som (m w indeksie górnym)."""
        (suggestion,) = by_code(propose("są"), "SUG-NAS-A-FINAL")
        assert suggestion.original == "ą"
        assert suggestion.replacement == "om"
        assert suggestion.superscript_ranges == ((1, 2),)
        assert suggestion.source == "rule"
        assert suggestion.confidence > 0
        assert suggestion.message

    def test_positions_point_at_source_character(self) -> None:
        text = "koty są dobre"
        (suggestion,) = by_code(propose(text), "SUG-NAS-A-FINAL")
        assert text[suggestion.start : suggestion.end] == "ą"


class TestNasalEBeforeDental:
    def test_e_ogonek_before_dental_proposes_superscript_n(self) -> None:
        """Przykład ze specyfikacji: będzie → bendzie."""
        suggestions = by_code(propose("będzie"), "SUG-NAS-E-DENT")
        assert len(suggestions) == 1
        assert suggestions[0].replacement == "en"
        assert suggestions[0].superscript_ranges == ((1, 2),)


class TestNasalBeforeLabial:
    def test_e_ogonek_before_labial(self) -> None:
        (suggestion,) = by_code(propose("zęba"), "SUG-NAS-E-LAB")
        assert suggestion.replacement == "em"

    def test_a_ogonek_before_labial(self) -> None:
        (suggestion,) = by_code(propose("ząb"), "SUG-NAS-A-LAB")
        assert suggestion.replacement == "om"


class TestLabialInitialO:
    def test_initial_o_proposes_superscript_u(self) -> None:
        """Przykład ze specyfikacji: od → uod."""
        (suggestion,) = by_code(propose("od"), "SUG-LAB-U-INIT")
        assert suggestion.replacement == "uo"
        assert suggestion.superscript_ranges == ((0, 1),)


class TestGuarantees:
    def test_no_candidates_for_plain_word(self) -> None:
        assert propose("mama") == []

    def test_input_is_not_mutated_and_result_sorted(self) -> None:
        text = "od są zęba"
        first = propose(text)
        assert propose(text) == first
        starts = [s.start for s in first]
        assert starts == sorted(starts)

    def test_every_candidate_has_source_and_confidence(self) -> None:
        for suggestion in propose("od są zęba ząb będzie"):
            assert suggestion.source == "rule"
            assert 0.0 < suggestion.confidence <= 1.0
            assert suggestion.message


class TestRuleCatalogue:
    def test_rules_expose_label_and_confidence_for_ui(self) -> None:
        from transkryptor.notation.suggestions import RULES

        assert {rule.code for rule in RULES} == {
            "SUG-NAS-A-FINAL",
            "SUG-NAS-E-DENT",
            "SUG-NAS-E-LAB",
            "SUG-NAS-A-LAB",
            "SUG-LAB-U-INIT",
        }
        assert all(rule.label and 0 < rule.confidence <= 1 for rule in RULES)


class TestWithoutOverlaps:
    def _suggestion(self, start: int, end: int, confidence: float):
        from transkryptor.notation.suggestions import Suggestion

        return Suggestion(
            code=f"X{start}",
            start=start,
            end=end,
            original="x" * (end - start),
            replacement="y",
            confidence=confidence,
        )

    def test_keeps_more_confident_of_overlapping(self) -> None:
        from transkryptor.notation.suggestions import without_overlaps

        weak = self._suggestion(0, 2, 0.3)
        strong = self._suggestion(1, 3, 0.5)
        separate = self._suggestion(3, 4, 0.1)
        assert without_overlaps([weak, strong, separate]) == [strong, separate]

    def test_real_rules_do_not_collide(self) -> None:
        from transkryptor.notation.suggestions import propose, without_overlaps

        text = "od są będzie zęby kąpie"
        assert without_overlaps(propose(text)) == propose(text)
