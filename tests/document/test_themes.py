"""Pola tematyczne: słowa kluczowe w tematach (zgłoszenie #51)."""

from transkryptor.document.speakers import INFORMANT, RESEARCHER, Speaker
from transkryptor.document.themes import (
    TextSource,
    Theme,
    builtin_themes,
    combined_fields,
    morfeusz_lemmatizer,
    plain_lemmatizer,
    speaker_sources,
    thematic_fields,
)

FARM = Theme("farm", {"pl": "Rolnictwo"}, frozenset({"krowa", "pole"}))
FUNERAL = Theme("funeral", {"pl": "Pogrzeb"}, frozenset({"pogrzeb", "trumna"}))
LEMMAS = {"krowy": ["krowa"], "krowę": ["krowa"], "polu": ["pole"]}


def fake_lemmatizer(word: str) -> list[str]:
    return LEMMAS.get(word.casefold(), [])


def test_builtin_themes_load() -> None:
    themes = builtin_themes()
    keys = {theme.key for theme in themes}
    assert {"agriculture", "home", "baptism", "funeral"} <= keys
    assert len(keys) == len(themes)
    for theme in themes:
        assert theme.label_text and theme.lemmas
        assert all(lemma == lemma.casefold() for lemma in theme.lemmas)


def test_words_are_counted_by_lemma_and_sorted_by_frequency() -> None:
    text = "Krowy na polu, krowę do obory. Potem pogrzeb."
    farm, funeral = thematic_fields(text, fake_lemmatizer, themes=(FUNERAL, FARM))
    assert farm.theme is FARM and farm.total == 3
    cow, field = farm.words
    assert (cow.lemma, cow.count, cow.forms) == ("krowa", 2, ("krowy", "krowę"))
    assert (field.lemma, field.count) == ("pole", 1)
    assert funeral.total == 1 and funeral.words[0].forms == ("pogrzeb",)


def test_only_given_ranges_count() -> None:
    text = "Pogrzeb?\nKrowy."
    (summary,) = thematic_fields(text, fake_lemmatizer, [(9, 15)], (FARM, FUNERAL))
    assert summary.theme is FARM


def test_without_lemmatizer_only_dictionary_forms_count() -> None:
    (summary,) = thematic_fields("krowa krowy", plain_lemmatizer, themes=(FARM,))
    assert summary.total == 1


def test_morfeusz_finds_themes_in_inflected_words() -> None:
    text = "Krowy pasłam na łące, potem był pogrzeb dziadka i chrzciny."
    found = {
        summary.theme.key: summary
        for summary in thematic_fields(text, morfeusz_lemmatizer())
    }
    assert {"agriculture", "funeral", "family", "baptism"} <= set(found)
    lemmas = {word.lemma for word in found["agriculture"].words}
    assert {"krowa", "łąka"} <= lemmas


def test_combined_sources_list_informants_by_first_use() -> None:
    sources = [
        TextSource("Krowy i pogrzeb.", speaker="Jan"),
        TextSource("Pogrzeb?\nKrowę.", [(9, 15)], "Anna"),
        TextSource("krowa", speaker="Jan"),
    ]
    farm, funeral = combined_fields(sources, fake_lemmatizer, (FARM, FUNERAL))
    (cow,) = farm.words
    assert (cow.count, cow.speakers) == (3, ("Jan", "Anna"))
    assert funeral.words[0].speakers == ("Jan",)


def test_speaker_sources_split_informants_and_name_them() -> None:
    speakers = (
        Speaker("B", "", RESEARCHER),
        Speaker("I", "Anna", INFORMANT),
        Speaker("I2", "", INFORMANT),
    )
    text = "Pytanie\nOdpowiedź\nInna\nDalej"
    sources = speaker_sources(text, {0: "B", 1: "I", 2: "I2", 3: "I"}, speakers, "w1")
    assert [(s.speaker, list(s.ranges or ())) for s in sources] == [
        ("Anna", [(8, 17), (23, 28)]),
        ("I2 (w1)", [(18, 22)]),
    ]


def test_speaker_sources_without_informants_use_whole_text() -> None:
    (source,) = speaker_sources("Krowa", {}, (), "w1")
    assert (source.text, source.ranges, source.speaker) == ("Krowa", None, "w1")
