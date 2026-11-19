"""Wnioski z poprawek szkicu ASR (zgłoszenie #74)."""

import re

from transkryptor.document.diff import Version
from transkryptor.notation.corpus_insights import ProjectEdits, corpus_insights
from transkryptor.notation.draft_insights import (
    Punctuation,
    draft_insights,
    extract_edits,
    suggested_settings,
)
from transkryptor.notation.rules import builtin_rules, dumps_rules, parse_dismissed
from transkryptor.notation.word_alignment import align_words, rewritten

BASELINE = (
    "Będzie często w piętrze. Ojciec, kiedy przyszedł, to było np. tak.\n"
    "No to tylko kartofle i kartofle.\n"
    "Często będzie kiedy.\n"
    "Kiedy będzie."
)
CORRECTED = (
    "bendzie czensto w pientrze ojciec kiej przyszedł to było na przykład tak nie?\n"
    "No no to ino grule i grule.\n"
    "czensto bendzie kiej nie?\n"
    "kiej nie bendzie."
)


def nasal(text: str) -> tuple[tuple[int, int], ...]:
    """„n” po „e” przed „dzie”/„sto”/„trze” w indeksie górnym."""
    return tuple(
        (m.start(), m.end()) for m in re.finditer(r"(?<=e)n(?=dzie|sto|trze)", text)
    )


def versions() -> tuple[Version, Version]:
    baseline = Version(BASELINE, (), {0: "B", 1: "I", 2: "I", 3: "I"})
    current = Version(CORRECTED, nasal(CORRECTED), {0: "B", 1: "B", 2: "I", 3: "I"})
    return baseline, current


def test_differences_are_split_by_kind() -> None:
    edits = extract_edits(*versions())
    pairs = [(i.correction.original, i.correction.corrected) for i in edits.corrections]
    assert pairs.count(("będzie", "bendzie")) == 3
    assert ("kiedy", "kiej") in pairs
    # Słowo przepisane w całości to kandydat do słownika, a nie reguła.
    assert [(p.original, p.corrected) for p in edits.phrases] == [
        ("tylko", "ino"),
        ("kartofle", "grule"),
        ("kartofle", "grule"),
    ]
    assert [p.corrected for p in edits.added] == ["nie", "no", "nie", "nie"]
    assert edits.punctuation == Punctuation(
        commas_removed=2, periods_removed=4, lowercased=4, abbreviations=1
    )
    assert [(e.paragraph, e.before, e.after) for e in edits.speakers] == [(1, "I", "B")]


def test_speakers_can_be_skipped_for_an_estimated_draft() -> None:
    assert not extract_edits(*versions(), speakers=False).speakers


def test_rule_proposals_with_places_and_dismissed_state() -> None:
    baseline, current = versions()
    rules = builtin_rules().rules
    insights = draft_insights(baseline, current, rules, min_repeats=2)
    nasal_rule = insights.rules[0]
    assert nasal_rule.candidate.change.key == ("ę", "e^n", "inner")
    # będzie (3×), często (2×) i piętrze
    assert len(nasal_rule.places) == nasal_rule.candidate.count == 6
    assert [(w.original, w.corrected, w.count) for w in insights.words] == [
        ("kartofle", "grule", 2)
    ]
    dismissed = draft_insights(
        baseline, current, rules, [("ę", "e^n", "inner")], min_repeats=2
    )
    assert dismissed.rules[0].dismissed


def test_uncorrected_matches_are_counted() -> None:
    baseline = Version("będzie raz, będzie dwa, będzie trzy, będzie cztery")
    text = "bendzie raz bendzie dwa bendzie trzy będzie cztery"
    current = Version(text, nasal(text))
    insights = draft_insights(baseline, current, ())
    assert insights.rules[0].unmatched == 1


def test_same_text_with_new_superscript_is_a_correction() -> None:
    baseline = Version("bendzie bendzie bendzie")
    current = Version(baseline.text, nasal(baseline.text))
    edits = extract_edits(baseline, current)
    assert len(edits.corrections) == 3
    assert draft_insights(baseline, current, ()).rules


def test_suggested_settings_follow_corrections() -> None:
    many = Punctuation(commas_removed=12, abbreviations=3)
    assert suggested_settings(6, many, verbatim=False, plain=False, expand=False) == (
        "verbatim",
        "lowercase_plain",
        "expand_abbreviations",
    )
    assert suggested_settings(6, many, verbatim=True, plain=True, expand=True) == ()
    assert (
        suggested_settings(1, Punctuation(), verbatim=False, plain=False, expand=False)
        == ()
    )


def test_align_words_pairs_similar_words_and_leaves_fillers() -> None:
    pairs, old, new = align_words(["Kiedy", "będzie"], ["kiej", "nie", "bendzie"])
    assert pairs == [(0, 0), (1, 2)]
    assert (old, new) == ([], [1])
    assert rewritten("tylko", "ino")
    assert not rewritten("kiedy", "kiej")


def test_corpus_sums_rare_patterns_across_projects() -> None:
    def project(name: str, words: int) -> ProjectEdits:
        baseline = Version(" ".join(["będzie"] * words))
        text = " ".join(["bendzie"] * words)
        return ProjectEdits(name, extract_edits(baseline, Version(text, nasal(text))))

    projects = [project("a", 2), project("b", 2), project("c", 1)]
    result = corpus_insights(projects, (), min_repeats=5, min_projects=2)
    rule = result.rules[0]
    assert (rule.candidate.count, rule.projects) == (5, 3)
    # W żadnym projekcie zmiana nie powtórzyła się trzy razy.
    assert rule.corpus_only
    assert not corpus_insights(projects, (), min_repeats=5, min_projects=4).rules
    assert corpus_insights(projects, (), [rule.candidate.change.key]).rules[0].dismissed


def test_dismissed_proposals_round_trip_in_the_rules_file() -> None:
    keys = [("ę", "e^n", "inner"), ('"', "\\^", "final")]
    raw = dumps_rules(builtin_rules().rules[:1], keys)
    assert parse_dismissed(raw) == tuple(keys)
    assert parse_dismissed("[[dismissed]]\nbefore = 1\n") == ()
    assert parse_dismissed("niepoprawny = [") == ()
