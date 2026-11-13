"""Części mowy słów według Morfeusza 2 (zgłoszenie #35)."""

import pytest

from transkryptor.document.parts_of_speech import (
    PRIORITY,
    TAG_CLASSES,
    PartOfSpeech,
    PartOfSpeechTagger,
    morfeusz_analyser,
)

FAKE_TAGS: dict[str, list[tuple[str, list[str]]]] = {
    "piec": [("subst:sg:nom.acc:m3", []), ("inf:imperf", [])],
    "kot": [("subst:sg:nom:m2", [])],
    "szybko": [("subst:sg:voc:f", []), ("adv:pos", [])],
    "do": [("prep:gen", []), ("subst:sg:nom:n:ncol", ["muz."])],
    "re": [("subst:sg:nom:n:ncol", ["muz."])],
    "w": [("prep:loc:nwok", [])],
    "som": [("ign", [])],
}


def fake_tagger(calls: list[str] | None = None) -> PartOfSpeechTagger:
    def analyse(word: str) -> list[tuple[str, list[str]]]:
        if calls is not None:
            calls.append(word)
        return FAKE_TAGS.get(word, [("ign", [])])

    return PartOfSpeechTagger(analyse)


def test_every_part_of_speech_has_tags_and_priority() -> None:
    assert set(TAG_CLASSES.values()) == set(PartOfSpeech)
    assert sorted(PRIORITY) == sorted(PartOfSpeech)


def test_ambiguous_word_gets_one_part_by_priority() -> None:
    tagger = fake_tagger()
    assert tagger.part_of("piec") == PartOfSpeech.VERB
    assert tagger.part_of("szybko") == PartOfSpeech.ADVERB
    assert tagger.part_of("som") is None


def test_qualified_interpretations_count_only_when_alone() -> None:
    tagger = fake_tagger()
    assert tagger.part_of("do") == PartOfSpeech.PREPOSITION
    assert tagger.part_of("re") == PartOfSpeech.NOUN


def test_spans_cover_only_wanted_parts() -> None:
    tagger = fake_tagger()
    text = "kot w piec, szybko som"
    spans = tagger.spans(text, (PartOfSpeech.NOUN, PartOfSpeech.ADVERB))
    assert [(text[s:e], part) for s, e, part in spans] == [
        ("kot", PartOfSpeech.NOUN),
        ("szybko", PartOfSpeech.ADVERB),
    ]
    assert tagger.spans(text, ()) == []


def test_each_word_is_analysed_once() -> None:
    calls: list[str] = []
    tagger = fake_tagger(calls)
    tagger.spans("kot kot kot", (PartOfSpeech.NOUN,))
    tagger.spans("kot", (PartOfSpeech.NOUN,))
    assert calls == ["kot"]


@pytest.mark.parametrize(
    ("word", "part"),
    [
        ("kota", PartOfSpeech.NOUN),
        ("Kot", PartOfSpeech.NOUN),
        ("szyje", PartOfSpeech.VERB),
        ("szybko", PartOfSpeech.ADVERB),
        ("piękne", PartOfSpeech.ADJECTIVE),
        ("No", PartOfSpeech.PARTICLE),
        ("do", PartOfSpeech.PREPOSITION),
        ("robiący", PartOfSpeech.VERB),
        ("zielony", PartOfSpeech.ADJECTIVE),
        ("bardzo", PartOfSpeech.ADVERB),
        ("on", PartOfSpeech.PRONOUN),
        ("dwa", PartOfSpeech.NUMERAL),
        ("w", PartOfSpeech.PREPOSITION),
        ("że", PartOfSpeech.CONJUNCTION),
        ("się", PartOfSpeech.PARTICLE),
        ("ach", PartOfSpeech.INTERJECTION),
    ],
)
def test_morfeusz_recognises_parts_of_speech(word, part) -> None:
    tagger = PartOfSpeechTagger(morfeusz_analyser())
    assert tagger.part_of(word) == part


def test_morfeusz_leaves_phonetic_forms_untagged() -> None:
    tagger = PartOfSpeechTagger(morfeusz_analyser())
    assert tagger.part_of("kuosa") is None
