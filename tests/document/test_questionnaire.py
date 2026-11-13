"""Kwestionariusz wywiadu (zgłoszenie #47)."""

from docx import Document as DocxDocument

from transkryptor.document.questionnaire import (
    QuestionMatcher,
    parse_questionnaire,
    read_questionnaire,
)

TEXT = """KOBIETA CIĘŻARNA
1. Skąd wiadomo, że kobieta jest w ciąży?
2) Jak się mówi na kobietę, która jest w ciąży?

- Rok i miejsce urodzenia
• Zajęcie osoby nagrywanej
"""


def test_parse_skips_numbering_blank_lines_and_headings() -> None:
    assert parse_questionnaire(TEXT) == (
        "Skąd wiadomo, że kobieta jest w ciąży?",
        "Jak się mówi na kobietę, która jest w ciąży?",
        "Rok i miejsce urodzenia",
        "Zajęcie osoby nagrywanej",
    )


def test_read_txt_and_docx(tmp_path) -> None:
    txt = tmp_path / "pytania.txt"
    txt.write_bytes(TEXT.encode("cp1250"))
    assert len(read_questionnaire(txt)) == 4
    document = DocxDocument()
    for line in TEXT.splitlines():
        document.add_paragraph(line)
    path = tmp_path / "pytania.docx"
    document.save(str(path))
    assert read_questionnaire(path) == read_questionnaire(txt)


def test_matcher_recognises_questions_without_question_mark() -> None:
    matcher = QuestionMatcher(parse_questionnaire(TEXT))
    assert matcher
    assert matcher.matches("Rok i miejsce urodzenia.")
    assert matcher.matches("A zajęcie osoby nagrywanej")
    assert matcher.matches("Jak się mówi na kobietę która jest w ciąży")
    # Odpowiedź z kilkoma słowami pytania, ale dłuższa - to nie pytanie.
    assert not matcher.matches(
        "Urodzenia to ja nie pamiętam roku ani miejsca dokładnie."
    )
    assert not matcher.matches("Rolnik.")
    assert not QuestionMatcher([])
