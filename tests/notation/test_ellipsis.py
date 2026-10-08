"""Testy stylu wielokropka (propozycja 14, faza 07)."""

from transkryptor.notation.ellipsis import (
    DEFAULT_ELLIPSIS_STYLE,
    EllipsisStyle,
    ellipsis_text,
    find_ellipses,
    foreign_ellipses,
    normalize_ellipses,
    pause_text,
)


def test_default_style_is_unicode() -> None:
    assert DEFAULT_ELLIPSIS_STYLE is EllipsisStyle.UNICODE


def test_texts_for_styles() -> None:
    assert ellipsis_text(EllipsisStyle.UNICODE) == "…"
    assert ellipsis_text(EllipsisStyle.ASCII) == "..."
    assert pause_text(EllipsisStyle.UNICODE) == " … "
    assert pause_text(EllipsisStyle.ASCII) == " ... "


def test_style_accepts_stored_string() -> None:
    assert ellipsis_text("ascii") == "..."  # type: ignore[arg-type]


def test_find_both_forms() -> None:
    text = "jeż... kam… tak ... bo"
    assert [text[s:e] for s, e in find_ellipses(text)] == ["...", "…", "..."]


def test_fixed_markers_are_skipped() -> None:
    assert find_ellipses("trzea [...] i […?] dalej") == []


def test_malformed_omitted_marker_is_left_to_val03() -> None:
    """`[…]` to błędny marker pominięcia (VAL-03), nie wielokropek do ujednolicenia."""
    assert find_ellipses("a […] b") == []


def test_foreign_ellipses() -> None:
    text = "a ... b … c"
    assert foreign_ellipses(text, EllipsisStyle.UNICODE) == [(2, 5)]
    assert foreign_ellipses(text, EllipsisStyle.ASCII) == [(8, 9)]


def test_normalize_to_unicode() -> None:
    text = "jeż... kam... rzeczy ... bo [...] […?]"
    assert (
        normalize_ellipses(text, EllipsisStyle.UNICODE)
        == "jeż… kam… rzeczy … bo [...] […?]"
    )


def test_normalize_to_ascii() -> None:
    assert normalize_ellipses("a … b…", EllipsisStyle.ASCII) == "a ... b..."


def test_normalize_is_identity_when_consistent() -> None:
    assert normalize_ellipses("a … b", EllipsisStyle.UNICODE) == "a … b"
