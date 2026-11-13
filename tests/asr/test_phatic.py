"""Fatyczne „nie?” odróżniane od pytań (zgłoszenie #45)."""

import pytest

from transkryptor.asr.phatic import ends_with_phatic_tag


@pytest.mark.parametrize(
    "sentence",
    [
        "Rodzice tu przywędrowali, się wybudowali, nie?",
        "No no, nie ma okresu i wiadomo, nie?",
        "No ciężarna, nie?",
        "tak przynajmniej mówią przez rowy nie?",
        "Tak było, co nie?",
        "Ładnie tu, prawda?",
        "nie wiem … nie? …",
    ],
)
def test_phatic_endings(sentence) -> None:
    assert ends_with_phatic_tag(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Nie?",
        "Gdzie pani mieszka?",
        "Czy kobieta w ciąży może patrzeć na ogień?",
        "A dlaczego nie?",  # „nie” po pytajniku „dlaczego” - pytanie
        "Rolnik.",
    ],
)
def test_real_questions_and_statements(sentence) -> None:
    assert not ends_with_phatic_tag(sentence)
