"""Testy porównania wersji na poziomie słów (faza 14, REQ-27)."""

import pytest

from transkryptor.document.diff import (
    DELETE,
    FORMAT,
    INSERT,
    REPLACE,
    SPEAKER,
    Change,
    Fragment,
    Version,
    apply_change,
    diff_versions,
    fragment,
    replace_fragment,
)
from transkryptor.document.model import Document


def apply_all(a: Version, b: Version) -> Version:
    """Przyjmuje wszystkie zmiany od końca, żeby pozycje się nie przesuwały."""
    result = a
    for change in sorted(
        diff_versions(a, b), key=lambda c: (c.a_start, c.kind != SPEAKER), reverse=True
    ):
        result = apply_change(result, b, change)
    return result


def test_identical_versions_have_no_changes() -> None:
    version = Version("ala ma kota\nnowy akapit", ((1, 2),), {0: "B", 1: "I"})
    assert diff_versions(version, version) == []


def test_acc_62_word_superscript_and_speaker() -> None:
    """ACC-62: słowo, indeks górny na jednym znaku i mówca → trzy zmiany."""
    a = Version("tak było\npamientam dobrze", (), {0: "B", 1: "I"})
    # „było” → „buło”, „m” w „pamientam” w indeksie górnym, mówca drugiego
    # akapitu B zamiast I.
    b = Version("tak buło\npamientam dobrze", ((11, 12),), {0: "B", 1: "B"})
    changes = diff_versions(a, b)
    assert [c.kind for c in changes] == [REPLACE, FORMAT, SPEAKER]
    word, superscript, speaker = changes
    assert a.text[word.a_start : word.a_end] == "było"
    assert b.text[word.b_start : word.b_end] == "buło"
    assert a.text[superscript.a_start : superscript.a_end] == "pamientam"
    assert (speaker.a_speaker, speaker.b_speaker) == ("I", "B")
    assert a.text[speaker.a_start : speaker.a_end] == "pamientam dobrze"
    assert apply_all(a, b) == b


def test_insert_and_delete() -> None:
    a = Version("ala ma kota")
    b = Version("ala ma bardzo kota")
    (change,) = diff_versions(a, b)
    assert change.kind == INSERT
    assert change.a_start == change.a_end == 7
    assert b.text[change.b_start : change.b_end] == "bardzo "

    (change,) = diff_versions(b, a)
    assert change.kind == DELETE
    assert b.text[change.a_start : change.a_end] == "bardzo "
    assert change.b_start == change.b_end
    assert apply_change(b, a, change) == a


def test_words_are_compared_separately() -> None:
    a = Version("ala ma kota")
    b = Version("ala miała psa")
    changes = diff_versions(a, b)
    assert [(c.kind, a.text[c.a_start : c.a_end]) for c in changes] == [
        (REPLACE, "ma"),
        (REPLACE, "kota"),
    ]
    assert apply_all(a, b) == b


def test_whitespace_change() -> None:
    a = Version("ala  ma")
    b = Version("ala ma")
    (change,) = diff_versions(a, b)
    assert change.kind == REPLACE
    assert apply_change(a, b, change) == b


def test_paragraphs_merge_and_split() -> None:
    a = Version("pierwszy\ndrugi", (), {0: "B", 1: "I"})
    b = Version("pierwszy drugi", (), {0: "B"})
    changes = diff_versions(a, b)
    assert [c.kind for c in changes] == [REPLACE]
    assert apply_all(a, b) == b

    # Podział akapitu: nowy akapit przejmuje mówcę z wersji B.
    changes = diff_versions(b, a)
    assert [c.kind for c in changes] == [REPLACE]
    assert apply_all(b, a) == a


def test_speakers_follow_unchanged_paragraphs() -> None:
    a = Version("wstęp\nraz\ndwa", (), {1: "B", 2: "I"})
    b = Version("raz\ndwa", (), {0: "B", 1: "B"})
    changes = diff_versions(a, b)
    assert [c.kind for c in changes] == [DELETE, SPEAKER]
    speaker = changes[1]
    assert a.text[speaker.a_start : speaker.a_end] == "dwa"
    assert (speaker.a_speaker, speaker.b_speaker) == ("I", "B")
    assert apply_all(a, b) == b


def test_inserted_paragraph_gets_speaker_from_b() -> None:
    a = Version("raz", (), {0: "I"})
    b = Version("nowy\nraz", (), {0: "B", 1: "I"})
    (change,) = diff_versions(a, b)
    assert change.kind == INSERT
    assert apply_change(a, b, change) == b
    # Cofnięcie (fragment A w miejsce fragmentu B) wraca do wersji A.
    assert diff_versions(b, a)[0].kind == DELETE
    assert apply_all(b, a) == a


def test_speaker_removed() -> None:
    a = Version("raz", (), {0: "I"})
    b = Version("raz")
    (change,) = diff_versions(a, b)
    assert change == Change(SPEAKER, 0, 3, 0, 3, "I", None)
    assert apply_change(a, b, change) == b


def test_format_change_removes_superscript() -> None:
    a = Version("sóᵐ tam", ((2, 3),))
    b = Version("sóᵐ tam")
    (change,) = diff_versions(a, b)
    assert change.kind == FORMAT
    assert apply_change(a, b, change) == b


def test_replaced_word_keeps_superscript_from_b() -> None:
    a = Version("kosa i")
    b = Version("kuosa i", ((1, 2),))
    (change,) = diff_versions(a, b)
    assert change.kind == REPLACE
    assert fragment(b, change.b_start, change.b_end) == Fragment(
        "kuosa", ((1, 2),), at_paragraph_start=True
    )
    assert apply_change(a, b, change) == b


def test_fragment_speakers_of_new_paragraphs() -> None:
    version = Version("a\nb\nc", (), {1: "I", 2: "B"})
    assert fragment(version, 1, 4).speakers == ("I", "B")
    assert fragment(version, 0, 1).speakers == ()


def test_replace_fragment_shifts_ranges() -> None:
    version = Version("ab cd ef", ((0, 1), (6, 7)))
    result = replace_fragment(version, 3, 5, Fragment("xyz", ((2, 3),)))
    assert result.text == "ab xyz ef"
    assert result.superscript_ranges == ((0, 1), (5, 6), (7, 8))


def test_from_document() -> None:
    document = Document(text="raz\ndwa", superscript_ranges=[(0, 1)])
    document.paragraph_speakers = {1: "I"}
    version = Version.from_document(document)
    assert version == Version("raz\ndwa", ((0, 1),), {1: "I"})


@pytest.mark.parametrize(
    ("a_text", "b_text"),
    [
        ("", "nowy tekst"),
        ("stary tekst", ""),
        ("raz dwa trzy", "trzy dwa raz"),
        ("a\n\nb", "a\nb\n"),
    ],
)
def test_apply_all_reaches_b(a_text: str, b_text: str) -> None:
    a = Version(a_text)
    b = Version(b_text)
    assert apply_all(a, b) == b


def test_punctuation_is_a_separate_token() -> None:
    a = Version("jak godoł, że")
    b = Version("jak godał, że")
    (change,) = diff_versions(a, b)
    assert a.text[change.a_start : change.a_end] == "godoł"
