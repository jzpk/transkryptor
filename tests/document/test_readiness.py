"""Raport gotowości do oddania (bez Qt)."""

from transkryptor.document.comments import new_comment
from transkryptor.document.metadata import MetadataField
from transkryptor.document.readiness import (
    COMMENTS,
    METADATA,
    SPEAKERS,
    UNCERTAIN,
    WARNINGS,
    build_report,
)
from transkryptor.notation.validator import Warning

TEXT = "B: tak było\nI: pamientam\n\ndobrze"


def test_empty_document_is_ready() -> None:
    assert build_report("").is_ready


def test_collects_every_category_in_text_order() -> None:
    open_comment = new_comment(3, 6, "tak", "A", "sprawdź")
    report = build_report(
        TEXT,
        warnings=[
            Warning("VAL-02", 20, 25, "druga"),
            Warning("VAL-01", 0, 1, "pierwsza"),
        ],
        uncertain=[(15, 24)],
        comments=[open_comment],
        paragraph_speakers={0: "B"},
        metadata={"signature": "S1", "place": " "},
        fields=(
            MetadataField("signature", "Sygnatura"),
            MetadataField("place", "Miejscowość"),
            MetadataField("district", "Powiat", enabled=False),
        ),
    )
    assert not report.is_ready
    assert [w.label for w in report.of(WARNINGS)] == [
        "VAL-01: pierwsza",
        "VAL-02: druga",
    ]
    assert [i.label for i in report.of(UNCERTAIN)] == ["pamientam"]
    assert [(i.label, i.start, i.end) for i in report.of(COMMENTS)] == [
        ("sprawdź", 3, 6)
    ]
    # Pusty akapit nie potrzebuje mówcy.
    assert [i.label for i in report.of(SPEAKERS)] == ["I: pamientam", "dobrze"]
    assert [i.field for i in report.of(METADATA)] == ["place"]


def test_resolved_comments_and_documents_without_speakers_pass() -> None:
    from dataclasses import replace

    resolved = replace(new_comment(0, 3, "B: ", "A", "ok"), resolved=True)
    report = build_report(TEXT, comments=[resolved], paragraph_speakers={})
    assert report.is_ready
