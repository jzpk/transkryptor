"""Testy mówców akapitów: model, projekt, walidator i wyszukiwanie (faza 12)."""

from typing import Any

import pytest

from transkryptor.document.model import Document
from transkryptor.document.project import (
    ProjectState,
    dumps,
    from_dict,
    loads,
    migrate,
)
from transkryptor.document.search import restrict_to
from transkryptor.document.speakers import (
    DEFAULT_SPEAKERS,
    INFORMANT,
    OTHER,
    RESEARCHER,
    Speaker,
    check_speakers,
    informant_spans,
    is_valid_key,
    legend,
    paragraph_spans,
    parse_legend,
)
from transkryptor.errors import ProjectError
from transkryptor.notation.validator import VAL_12, validate

I2 = Speaker("I2", "AK", INFORMANT)


def test_paragraph_spans() -> None:
    assert paragraph_spans("") == [(0, 0)]
    assert paragraph_spans("ab\ncd\n") == [(0, 2), (3, 5), (6, 6)]


def test_keys_and_validation() -> None:
    assert is_valid_key("B") and is_valid_key("I2") and is_valid_key("Ł1")
    assert not is_valid_key("") and not is_valid_key("B:") and not is_valid_key("a b")
    assert not is_valid_key("ABCDEFGHI")
    with pytest.raises(ValueError):
        check_speakers([Speaker("B"), Speaker("B")])
    with pytest.raises(ValueError):
        check_speakers([Speaker("B", role="nikt")])


class TestDocument:
    def test_defaults_are_researcher_and_informant(self) -> None:
        document = Document()
        assert [(s.key, s.role) for s in document.speakers] == [
            ("B", RESEARCHER),
            ("I", INFORMANT),
        ]
        assert document.paragraph_speakers == {}

    def test_assignments_are_cleaned(self) -> None:
        document = Document(text="a\nb", paragraph_speakers={0: "B", 1: "X", 5: "I"})
        assert document.paragraph_speakers == {0: "B"}

    def test_replace_all_keeps_assignments_when_not_given(self) -> None:
        document = Document(text="a\nb", paragraph_speakers={1: "I"})
        assert document.replace_all("a\nbb", [])
        assert document.paragraph_speakers == {1: "I"}
        revision = document.revision
        assert document.replace_all("a\nbb", [], {0: "B", 1: "I"})
        assert document.revision == revision + 1
        assert not document.replace_all("a\nbb", [], {0: "B", 1: "I"})

    def test_replace_shifts_and_merges_paragraphs(self) -> None:
        document = Document(text="a\nb\nc", paragraph_speakers={0: "B", 1: "I", 2: "B"})
        # Podział akapitu: mówca zostaje przy pierwszej części, druga jest bez mówcy.
        document.replace(0, 0, "x\n")
        assert document.text == "x\na\nb\nc"
        assert document.paragraph_speakers == {0: "B", 2: "I", 3: "B"}
        document.replace(1, 4, "")  # scala akapity 0, 1 i 2 („x” + „b”)
        assert document.text == "xb\nc"
        assert document.paragraph_speakers == {0: "B", 1: "B"}

    def test_set_speakers_renames_and_removes(self) -> None:
        document = Document(text="a\nb\nc", paragraph_speakers={0: "B", 1: "I", 2: "I"})
        revision = document.revision
        document.set_speakers([Speaker("R", "", RESEARCHER)], {"B": "R"})
        assert document.paragraph_speakers == {0: "R"}
        assert document.revision == revision + 1
        assert document.speaker("R") is not None and document.speaker("I") is None


def test_legend_round_trip_and_anonymization() -> None:
    speakers = [*DEFAULT_SPEAKERS, I2, Speaker("X", "", OTHER)]
    text = legend(speakers)
    assert text == "B — Badacz; I — Informator; I2 — AK; X — Inny"
    assert parse_legend(text) == speakers
    assert legend(speakers, anonymize=True).split("; ")[2] == "I2 — Informator"


def test_informant_spans_and_search_filter() -> None:
    text = "pytanie\nodpowiedź pierwsza\ndrugie pytanie\nodpowiedź"
    assignments = {0: "B", 1: "I", 2: "B", 3: "I2"}
    spans = informant_spans(text, assignments, [*DEFAULT_SPEAKERS, I2])
    assert spans == [(8, 26), (42, 51)]
    matches = [(0, 7), (8, 17), (36, 43), (42, 51)]
    assert restrict_to(matches, spans) == [(8, 17), (42, 51)]


class TestValidator:
    def test_missing_speaker_only_when_speakers_are_used(self) -> None:
        text = "pytanie\n  odpowiedź tak\n\nkoniec"
        assert not [w for w in validate(text) if w.code == VAL_12]
        warnings = [
            w for w in validate(text, paragraph_speakers={0: "B"}) if w.code == VAL_12
        ]
        assert [(text[w.start : w.end], w.severity) for w in warnings] == [
            ("odpowiedź", "hint"),
            ("koniec", "hint"),
        ]

    def test_rule_can_be_disabled(self) -> None:
        warnings = validate("a\nb", enabled=set(), paragraph_speakers={0: "B"})
        assert warnings == []


class TestProject:
    def test_round_trip(self) -> None:
        state = ProjectState(
            text="pytanie\nodpowiedź",
            speakers=(*DEFAULT_SPEAKERS, I2),
            paragraph_speakers={0: "B", 1: "I2"},
        )
        restored = loads(dumps(state))
        assert restored.speakers == state.speakers
        assert restored.paragraph_speakers == {0: "B", 1: "I2"}

    def test_schema_4_gets_default_speakers(self) -> None:
        data: dict[str, Any] = {
            "schema_version": 4,
            "document": {"text": "a\nb"},
            "anchors": [],
        }
        migrated = migrate(data)
        assert migrated["schema_version"] == 5
        assert "speakers" not in data["document"]  # wejście bez zmian
        state = from_dict(data)
        assert state.speakers == DEFAULT_SPEAKERS
        assert state.paragraph_speakers == {}

    @pytest.mark.parametrize(
        "assignments",
        [[[2, "B"]], [[0, "X"]], [[0, "B"], [0, "I"]], [[0]], [["0", "B"]]],
    )
    def test_invalid_assignments_are_rejected(self, assignments) -> None:
        data = from_dict_input("a\nb", assignments)
        with pytest.raises(ProjectError):
            from_dict(data)

    def test_invalid_speaker_is_rejected(self) -> None:
        data = from_dict_input("a", [])
        data["document"]["speakers"] = [{"key": "B:", "label": "", "role": "other"}]
        with pytest.raises(ProjectError):
            from_dict(data)


def from_dict_input(text: str, assignments: list) -> dict:
    return {
        "schema_version": 5,
        "document": {
            "text": text,
            "speakers": [{"key": "B"}, {"key": "I", "role": "informant"}],
            "paragraph_speakers": assignments,
        },
    }
