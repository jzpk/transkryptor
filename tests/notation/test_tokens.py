"""Testy tokenizacji elementów notacji."""

from transkryptor.notation.tokens import TokenKind, tokenize


def kinds(text: str) -> list[TokenKind]:
    return [token.kind for token in tokenize(text)]


def test_plain_words() -> None:
    assert kinds("pamientam kuosa") == [TokenKind.WORD, TokenKind.WORD]


def test_pause_with_spaces() -> None:
    """`takich rzeczy ... bo` — pauza z odstępem po obu stronach."""
    assert kinds("takich rzeczy ... bo") == [
        TokenKind.WORD,
        TokenKind.WORD,
        TokenKind.PAUSE,
        TokenKind.WORD,
    ]


def test_cut_off_word() -> None:
    """`jeż... kam... kamionka` — urwane słowa, nie pauzy."""
    assert kinds("jeż... kam... kamionka") == [
        TokenKind.WORD,
        TokenKind.CUT_OFF,
        TokenKind.WORD,
        TokenKind.CUT_OFF,
        TokenKind.WORD,
    ]


def test_oddity_and_doubt_markers() -> None:
    assert kinds("zamudze (!) pani") == [
        TokenKind.WORD,
        TokenKind.ODDITY,
        TokenKind.WORD,
    ]
    assert kinds("nogie (?) dogioł") == [
        TokenKind.WORD,
        TokenKind.DOUBT,
        TokenKind.WORD,
    ]


def test_omitted_marker() -> None:
    assert kinds("odstraszy […?] inne ptaki") == [
        TokenKind.WORD,
        TokenKind.OMITTED,
        TokenKind.WORD,
        TokenKind.WORD,
    ]


def test_aside_brackets() -> None:
    assert kinds("trzea [świnię]") == [
        TokenKind.WORD,
        TokenKind.ASIDE_OPEN,
        TokenKind.WORD,
        TokenKind.ASIDE_CLOSE,
    ]


def test_ellipsis_at_text_start_followed_by_word() -> None:
    assert kinds("...początek") == [TokenKind.ELLIPSIS, TokenKind.WORD]


def test_ellipsis_at_text_end_is_pause() -> None:
    assert kinds("koniec ...") == [TokenKind.WORD, TokenKind.PAUSE]


def test_single_ellipsis_character_is_pause() -> None:
    """ACC-23: `…` z odstępami to pauza, tak samo jak ` ... `."""
    assert kinds("coś … coś") == [TokenKind.WORD, TokenKind.PAUSE, TokenKind.WORD]


def test_single_ellipsis_character_after_word_is_cut_off() -> None:
    """ACC-23: `jeż… kam… kamionka` — urwane słowa zapisane znakiem `…`."""
    assert kinds("jeż… kam… kamionka") == [
        TokenKind.WORD,
        TokenKind.CUT_OFF,
        TokenKind.WORD,
        TokenKind.CUT_OFF,
        TokenKind.WORD,
    ]


def test_single_ellipsis_character_before_word() -> None:
    assert kinds("…bo") == [TokenKind.ELLIPSIS, TokenKind.WORD]


def test_positions_are_preserved() -> None:
    text = "jeż... ...bo"
    tokens = tokenize(text)
    assert [(t.start, t.end, t.text) for t in tokens] == [
        (0, 3, "jeż"),
        (3, 6, "..."),
        (7, 10, "..."),
        (10, 12, "bo"),
    ]
    assert tokens[1].kind is TokenKind.CUT_OFF
    assert tokens[2].kind is TokenKind.ELLIPSIS
