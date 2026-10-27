"""Pliki zapisane poprzednim wydaniem otwierają się w bieżącej wersji.

``data/wywiad-v0.6.0.transkr`` i ``data/wywiad-v0.6.0.docx`` zapisał kod
wydania 0.6.0 (opis w ``data/README.md``). Użytkownik po aktualizacji
programu musi odzyskać z nich całą pracę: tekst z indeksem górnym, mówców,
metryczkę, kotwice czasowe, szkic ASR i nagranie.
"""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog
from tests.e2e.conftest import DATA_DIR

from transkryptor.document.anchors import SEGMENT, WORD, Anchor
from transkryptor.document.speakers import INFORMANT, OTHER, RESEARCHER, Speaker
from transkryptor.ui.main_window import MainWindow

PROJECT = DATA_DIR / "wywiad-v0.6.0.transkr"
DOCX = DATA_DIR / "wywiad-v0.6.0.docx"

TEXT = (
    "Jak tu było za młodu?\n"
    "No to tak... uod tego czasu som tu, bendzie z pińćdziesiont lat.\n"
    "A brat?\n"
    "Brat poszed do miasta."
)
SUPERSCRIPTS = ["u", "m", "n"]
SPEAKERS = (
    Speaker("B", "", RESEARCHER),
    Speaker("I", "Janina K.", INFORMANT),
    Speaker("S", "sąsiadka", OTHER),
)
PARAGRAPH_SPEAKERS = {0: "B", 1: "I", 2: "S", 3: "I"}
METADATA = {"signature": "WP-0042", "place": "Ocieszyn", "district": "wałecki"}


def superscripts(window: MainWindow) -> list[str]:
    text = window.document.text
    return [text[start:end] for start, end in window.document.superscript_ranges]


def test_project_from_previous_release_opens_with_all_work(
    qtbot, add_window, tmp_path, monkeypatch, no_blocking_dialogs
) -> None:
    window = add_window(MainWindow())
    assert window.session.open_project(PROJECT)
    qtbot.waitUntil(lambda: window.player_bar.has_media, timeout=10000)

    assert window.editor.toPlainText() == TEXT
    assert superscripts(window) == SUPERSCRIPTS
    assert tuple(window.document.speakers) == SPEAKERS
    assert window.document.paragraph_speakers == PARAGRAPH_SPEAKERS
    assert window.document.metadata == METADATA
    assert window.author_edit.text() == "Anna Nowak"
    assert window.document.date == "2026-10-08"
    assert window.asr_panel.transcription.segments_list.count() == 2
    assert not window.document.is_unsaved and not window.document.is_dirty

    state = window.session.capture_state()
    assert state.anchors[:3] == (
        Anchor(0, 21, 0, 1800, SEGMENT),
        Anchor(22, 86, 1900, 6200, SEGMENT),
        Anchor(87, 94, 6300, 7100, SEGMENT),
    )
    assert state.anchors[3] == Anchor(95, 99, 7200, 7600, WORD, 0.42)
    assert state.player.position_ms == 1500
    assert (state.player.loop_a_ms, state.player.loop_b_ms) == (1000, 3000)
    assert state.audio is not None and state.audio.name == "sample.mp3"
    assert not [call for call in no_blocking_dialogs if call[0] != "information"]

    # Zapis w bieżącym formacie i ponowne otwarcie nic nie gubi.
    target = tmp_path / "wywiad.transkr"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "")),
    )
    window.session.save_project_as()
    reopened = add_window(MainWindow())
    assert reopened.session.open_project(target)
    qtbot.waitUntil(lambda: reopened.player_bar.has_media, timeout=10000)
    again = reopened.session.capture_state()
    assert again.text == state.text
    assert again.superscript_ranges == state.superscript_ranges
    assert again.speakers == state.speakers
    assert again.paragraph_speakers == state.paragraph_speakers
    assert again.metadata == state.metadata
    assert again.anchors == state.anchors
    assert again.asr == state.asr
    assert again.audio is not None and Path(again.audio.absolute_path).samefile(
        state.audio.absolute_path
    )


def test_docx_from_previous_release_imports_text_speakers_and_metadata(
    add_window, no_blocking_dialogs
) -> None:
    """DOCX 0.6.0 ma legendę mówców z pauzą (U+2014) - import musi ją czytać."""
    window = add_window(MainWindow())
    assert window.session.import_docx(DOCX, confirm=False)

    assert window.editor.toPlainText() == TEXT
    assert superscripts(window) == SUPERSCRIPTS
    assert tuple(window.document.speakers) == SPEAKERS
    assert window.document.paragraph_speakers == PARAGRAPH_SPEAKERS
    assert window.document.metadata == METADATA
    assert window.author_edit.text() == "Anna Nowak"
    assert window.document.date == "2026-10-08"
    assert [call[0] for call in no_blocking_dialogs] == ["information"]
