"""Pola tematyczne: słowa kluczowe w tematach (zgłoszenie #51)."""

from transkryptor.document.themes import (
    Theme,
    builtin_themes,
    morfeusz_lemmatizer,
    plain_lemmatizer,
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
