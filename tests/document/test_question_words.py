"""Słowa według pytań kwestionariusza (zgłoszenie #72)."""

from dataclasses import replace

from transkryptor.document.parts_of_speech import (
    Interpretation,
    PartOfSpeech,
    PartOfSpeechTagger,
)
from transkryptor.document.question_words import (
    OUTSIDE,
    QuestionLocator,
    WordOptions,
    WordsSource,
    question_words,
)
from transkryptor.document.questionnaire import QuestionMark
from transkryptor.document.speakers import DEFAULT_SPEAKERS

NOUN, VERB = PartOfSpeech.NOUN, PartOfSpeech.VERB

DICTIONARY: dict[str, list[Interpretation]] = {
    "cepem": [("subst:sg:inst:m3", [], "cep:Sm3")],
    "klepisku": [("subst:sg:loc:n2", [], "klepisko")],
    "młóciło": [("praet:sg:n:imperf", [], "młócić")],
    "ziarno": [("subst:sg:nom:n2", [], "ziarno")],
    "sąsieku": [("subst:sg:loc:m3", [], "sąsiek")],
    # Bez kontekstu „piec” to czasownik, ale bywa rzeczownikiem.
    "piec": [("inf:imperf", [], "piec"), ("subst:sg:nom:m3", [], "piec:Sm3")],
    "chleb": [("subst:sg:acc:m3", [], "chleb")],
    "w": [("prep:loc", [], "w")],
    "się": [("qub", [], "się")],
    "było": [("praet:sg:n:imperf", [], "być")],
}

QUESTIONS = (
    "Jak wyglądało młócenie zboża?",
    "Gdzie przechowywano ziarno?",
    "Jak się piekło chleb?",
    "Jak chowano zmarłych?",
)

TEXT = "\n".join(
    (
        "Jak wyglądało młócenie zboża?",
        "Młóciło cepem w klepisku, bijok.",
        "A gdzie przechowywano ziarno?",
        "Ziarno w sąsieku.",
        "Jak się piekło chleb?",
        "Chleb, piec.",
        "A co jeszcze?",
        "Ziarno.",
    )
)
SPEAKERS = {0: "B", 1: "I", 2: "B", 3: "I", 4: "B", 5: "I", 6: "B", 7: "I"}


def analyse(word: str) -> list[Interpretation]:
    return DICTIONARY.get(word.lower(), [("ign", [], word)])


def tagger() -> PartOfSpeechTagger:
    return PartOfSpeechTagger(analyse)


def source(**changes: object) -> WordsSource:
    base = WordsSource("wywiad", TEXT, SPEAKERS, DEFAULT_SPEAKERS, QUESTIONS)
    return replace(base, **changes)  # type: ignore[arg-type]  # pola WordsSource


def lemmas(section) -> list[tuple[str, PartOfSpeech | None]]:
    return [(word.lemma, word.part) for word in section.words]


def test_answers_are_split_by_questions_and_only_informants_count() -> None:
    result = question_words([source()], tagger())
    numbers = [section.number for section in result.sections]
    assert numbers == [1, 2, 3]
    first, second, third = result.sections
    assert first.place is not None and first.place.paragraph == 0
    assert not first.place.manual
    assert lemmas(first) == [("bijok", None), ("cep", NOUN), ("klepisko", NOUN)]
    # Słowo z pytania badacza („ziarno”) nie liczy się do odpowiedzi.
    assert [word.count for word in second.words] == [1, 1]
    # Ostatnie pytanie trwa do końca tekstu (także „A co jeszcze?”).
    assert ("ziarno", NOUN) in lemmas(third)
    # Informator bez etykiety: klucz i nazwa projektu (jak w polach tematycznych).
    assert third.words[0].speakers == ("I (wywiad)",)


def test_words_carry_thematic_fields_and_forms() -> None:
    result = question_words([source()], tagger())
    cep = next(word for word in result.sections[0].words if word.lemma == "cep")
    assert cep.theme == "Rolnictwo i praca w polu"
    assert cep.forms == ("cepem",)
    klepisko = next(w for w in result.sections[0].words if w.lemma == "klepisko")
    assert klepisko.theme == ""


def test_unlocated_question_is_folded_into_the_previous_one() -> None:
    result = question_words([source()], tagger())
    assert [(q.number, q.folded_into) for q in result.unlocated] == [(4, 3)]
    assert result.sections[-1].folded == (4,)


def test_ambiguous_words_only_count_in_the_fuller_list() -> None:
    exact = question_words([source()], tagger(), WordOptions(frozenset({NOUN})))
    assert ("piec", NOUN) not in lemmas(exact.sections[2])
    full = question_words([source()], tagger(), WordOptions(frozenset({NOUN}), True))
    piec = next(w for w in full.sections[2].words if w.lemma == "piec")
    assert piec.part is NOUN and piec.ambiguous
    verbs = question_words([source()], tagger(), WordOptions(frozenset({VERB})))
    assert ("piec", VERB) in lemmas(verbs.sections[2])
    assert not next(w for w in verbs.sections[2].words if w.lemma == "piec").ambiguous


def test_manual_mark_overrides_the_recognised_paragraph() -> None:
    marks = (QuestionMark(3, "A co jeszcze?"),)
    result = question_words([source(marks=marks)], tagger())
    numbers = [section.number for section in result.sections]
    assert numbers == [1, 2, 3, 4]
    fourth = result.sections[-1]
    assert fourth.place is not None and fourth.place.manual
    assert fourth.asked == "A co jeszcze?"
    assert lemmas(fourth) == [("ziarno", NOUN)]
    assert not result.unlocated


def test_mark_with_changed_paragraph_is_reported_as_lost() -> None:
    marks = (QuestionMark(3, "Ten akapit już nie istnieje"),)
    result = question_words([source(marks=marks)], tagger())
    assert result.lost_marks == marks
    assert [q.number for q in result.unlocated] == [4]


def test_without_speakers_the_answer_starts_after_the_question_sentence() -> None:
    text = "Gdzie przechowywano ziarno? W sąsieku.\nJak się piekło chleb? Piec."
    result = question_words(
        [source(text=text, paragraph_speakers={})],
        tagger(),
        WordOptions(frozenset({NOUN}), True),
    )
    assert [section.number for section in result.sections] == [2, 3]
    assert lemmas(result.sections[0]) == [("sąsiek", NOUN)]
    assert lemmas(result.sections[1]) == [("piec", NOUN)]


def test_words_before_the_first_question_are_outside() -> None:
    text = "Ziarno było.\n" + TEXT
    speakers = {0: "I", **{index + 1: key for index, key in SPEAKERS.items()}}
    result = question_words([source(text=text, paragraph_speakers=speakers)], tagger())
    assert result.sections[0].number == OUTSIDE
    assert lemmas(result.sections[0]) == [("ziarno", NOUN)]


def test_joined_sources_merge_answers_to_the_same_question() -> None:
    other = WordsSource(
        "inny",
        "Gdzie przechowywano ziarno?\nW sąsieku.",
        {0: "B", 1: "I"},
        DEFAULT_SPEAKERS,
        ("Gdzie przechowywano ziarno?",),
    )
    result = question_words([source(), other], tagger())
    second = next(section for section in result.sections if section.number == 2)
    sasiek = next(word for word in second.words if word.lemma == "sąsiek")
    assert sasiek.count == 2


def test_candidates_rank_researcher_paragraphs_by_similarity() -> None:
    locator = QuestionLocator(source())
    candidates = locator.candidates(1)
    assert candidates[0].paragraph == 2
    # Akapity informatorów nie są kandydatami.
    assert all(candidate.paragraph % 2 == 0 for candidate in candidates)
