"""Wspólne dane testów korpusu: folder z projektami."""

from pathlib import Path

import pytest

from transkryptor.document.anchors import SEGMENT, WORD, Anchor
from transkryptor.document.project import AudioRef, ProjectState, save_project

# „bendzie” z „b” w indeksie górnym; akapit 0 - badacz, 1 - informator.
TEXT_A = "Jag to było?\nNo bendzie jak było"
SUPERSCRIPT_A = ((16, 17),)
ANCHORS_A = (
    Anchor(0, 12, 0, 2000, SEGMENT),
    Anchor(13, 32, 2000, 6000, SEGMENT),
    Anchor(24, 27, 4000, 4500, WORD, probability=0.9),
)
TEXT_B = "jak tak to tak"


def project_a() -> ProjectState:
    return ProjectState(
        text=TEXT_A,
        superscript_ranges=SUPERSCRIPT_A,
        author="Anna",
        date="2026-10-01",
        metadata={
            "signature": "AdK_1954",
            "place": "Brzezie",
            "district": "Kłaj",
            "informant": "INF-7",
            "recording_date": "1954-07-12",
            "custom-x": "dodatkowe",
        },
        paragraph_speakers={0: "B", 1: "I"},
        anchors=ANCHORS_A,
        audio=AudioRef("/nagrania/AdK_1954.wav", "abc123"),
    )


@pytest.fixture
def state_a() -> ProjectState:
    return project_a()


@pytest.fixture
def corpus_dir(tmp_path) -> Path:
    save_project(project_a(), tmp_path / "AdK_1954.transkr")
    (tmp_path / "wies").mkdir()
    save_project(ProjectState(text=TEXT_B), tmp_path / "wies" / "B_1960.transkr")
    (tmp_path / "uszkodzony.transkr").write_text("{", encoding="utf-8")
    (tmp_path / ".ukryty").mkdir()
    save_project(ProjectState(text="jak"), tmp_path / ".ukryty" / "x.transkr")
    return tmp_path
