"""Testy wyszukiwania i składni zamiennika (propozycja 20, faza 07)."""

import time

import pytest

from transkryptor.document.search import (
    MAX_MATCHES,
    MAX_PATTERN_LENGTH,
    ParsedReplacement,
    SearchError,
    SearchOptions,
    compile_query,
    find_all,
    parse_replacement,
)


def spans(text: str, query: str, **options) -> list[tuple[int, int]]:
    return find_all(text, compile_query(query, SearchOptions(**options)))


class TestFind:
    def test_plain_text_is_case_insensitive_by_default(self) -> None:
        assert spans("Będzie i będzie", "będzie") == [(0, 6), (9, 15)]

    def test_case_sensitive(self) -> None:
        assert spans("Będzie i będzie", "będzie", case_sensitive=True) == [(9, 15)]

    def test_whole_words(self) -> None:
        text = "będzie będziesz będzie"
        assert spans(text, "będzie", whole_words=True) == [(0, 6), (16, 22)]

    def test_plain_text_escapes_regex_characters(self) -> None:
        assert spans("a (?) b ... c", "(?)") == [(2, 5)]
        assert spans("a ... b", "...") == [(2, 5)]

    def test_regex(self) -> None:
        assert spans("som sóm sam", "s[oó]m", regex=True) == [(0, 3), (4, 7)]

    def test_regex_with_whole_words_and_alternation(self) -> None:
        assert spans("tak taki nie", "tak|nie", regex=True, whole_words=True) == [
            (0, 3),
            (9, 12),
        ]

    def test_empty_matches_are_skipped(self) -> None:
        assert spans("abc", "x*", regex=True) == []

    def test_match_limit(self) -> None:
        assert len(spans("a" * (MAX_MATCHES + 5), "a")) == MAX_MATCHES


class TestQueryErrors:
    def test_invalid_regex(self) -> None:
        """ACC-27: błędny regex to komunikat, nie wyjątek spoza modułu."""
        with pytest.raises(SearchError, match="wyrażenie"):
            compile_query("(", SearchOptions(regex=True))

    def test_invalid_regex_is_fine_as_plain_text(self) -> None:
        assert spans("a ( b", "(") == [(2, 3)]

    def test_pattern_length_limit(self) -> None:
        with pytest.raises(SearchError, match="długi"):
            compile_query("a" * (MAX_PATTERN_LENGTH + 1), SearchOptions())


class TestReplacement:
    def test_plain(self) -> None:
        assert parse_replacement("som") == ParsedReplacement("som", ())

    def test_superscript_char(self) -> None:
        """ACC-26: `be^ndzie` → `bendzie` z `n` w indeksie górnym."""
        assert parse_replacement("be^ndzie") == ParsedReplacement("bendzie", ((2, 3),))

    def test_adjacent_superscripts_merge(self) -> None:
        assert parse_replacement("^u^od") == ParsedReplacement("uod", ((0, 2),))

    def test_separate_superscripts(self) -> None:
        assert parse_replacement("^ua^m") == ParsedReplacement("uam", ((0, 1), (2, 3)))

    def test_escaped_caret(self) -> None:
        assert parse_replacement(r"a\^b") == ParsedReplacement("a^b", ())

    def test_trailing_caret_is_error(self) -> None:
        with pytest.raises(SearchError):
            parse_replacement("abc^")

    def test_backslash_alone_is_literal(self) -> None:
        assert parse_replacement("a\\b") == ParsedReplacement("a\\b", ())


class TestCatastrophicPatterns:
    """SEC-03: wzorzec z katastrofalnym nawrotem nie zawiesza wyszukiwania."""

    @pytest.mark.parametrize(
        ("pattern", "text"),
        [(r"(a|aa)+$", "a" * 60 + "b"), (r"(a+)+$", "a" * 30 + "b")],
    )
    def test_expensive_pattern_stops_within_limit(self, pattern, text) -> None:
        compiled = compile_query(pattern, SearchOptions(regex=True))
        started = time.monotonic()
        try:
            find_all(text, compiled)
        except SearchError as error:
            assert "zbyt kosztowny" in str(error)
        assert time.monotonic() - started < 1.0

    def test_timeout_is_shared_by_all_matches(self) -> None:
        # Każde pojedyncze dopasowanie jest tanie, ale razem przekraczają limit.
        compiled = compile_query("a", SearchOptions())
        with pytest.raises(SearchError, match="zbyt kosztowny"):
            find_all("a" * 5000, compiled, timeout_s=0.0)

    def test_lookbehind_sees_text_before_search_position(self) -> None:
        assert spans("xab ab", "ab", whole_words=True) == [(4, 6)]
