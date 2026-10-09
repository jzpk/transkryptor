"""Testy not wydania: komplet informacji wymagany przez fazę 05."""

from datetime import date

from transkryptor.packaging import metadata
from transkryptor.packaging.checksums import Checksum
from transkryptor.packaging.release_notes import render_release_notes

LINUX = Checksum(
    name=metadata.targets()["linux"].artifact_name,
    digest="a" * 64,
    size_bytes=187_000_000,
)
WINDOWS = Checksum(
    name=metadata.targets()["windows"].artifact_name,
    digest="b" * 64,
    size_bytes=210_000_000,
)


def test_notes_cover_every_required_section() -> None:
    notes = render_release_notes([LINUX, WINDOWS], whats_new="- Zmiana.")
    for heading in (
        "## Nowości w tej wersji",
        "## Artefakty",
        "## Instalacja",
        "## Prywatność",
        "## Model ASR",
        "## Wymagania sprzętowe",
        "## Znane ograniczenia",
        "## Licencje",
    ):
        assert heading in notes


def test_artifact_table_lists_checksums_and_platforms() -> None:
    notes = render_release_notes([LINUX, WINDOWS])
    assert LINUX.digest in notes
    assert WINDOWS.digest in notes
    assert "Linux (x86_64, AppImage)" in notes
    assert "Windows 10/11 (x64)" in notes


def test_powershell_hint_appears_only_with_the_windows_artifact() -> None:
    assert "Get-FileHash" not in render_release_notes([LINUX])
    assert "Get-FileHash" in render_release_notes([WINDOWS])


def test_notes_state_that_python_is_not_required() -> None:
    """Bramka zakończenia fazy: artefakt działa bez globalnego Pythona."""
    notes = render_release_notes([LINUX, WINDOWS])
    assert "Python nie musi być zainstalowany" in notes


def test_privacy_section_states_there_is_no_telemetry() -> None:
    notes = render_release_notes([LINUX])
    assert "nie zbiera telemetrii" in notes
    assert "bez dostępu do Internetu" in notes


def test_model_section_explains_consent_and_location() -> None:
    notes = render_release_notes([LINUX])
    assert "Systran/faster-whisper-medium" in notes
    assert "po potwierdzeniu" in notes
    assert "%APPDATA%\\Transkryptor\\models" in notes
    assert "~/.local/share/transkryptor/models" in notes


def test_hardware_table_comes_from_one_source_of_truth() -> None:
    notes = render_release_notes([LINUX])
    for requirement in metadata.HARDWARE_REQUIREMENTS:
        assert requirement.minimum in notes


def test_limitations_name_the_asr_draft_as_orthographic() -> None:
    notes = render_release_notes([LINUX])
    assert "ortograficzną" in notes
    assert "korpusie referencyjnym" in notes
    assert "MP3" in notes


def test_source_url_is_rendered_when_known() -> None:
    notes = render_release_notes([LINUX], source_url="https://example.org/repo")
    assert "<https://example.org/repo>" in notes


def test_source_section_survives_a_missing_url() -> None:
    notes = render_release_notes([LINUX])
    assert "### Kod źródłowy" in notes
    assert metadata.PUBLISHER in notes


def test_release_date_is_explicit() -> None:
    notes = render_release_notes([LINUX], release_date=date(2026, 1, 31))
    assert "2026-01-31" in notes


def test_version_drives_the_heading() -> None:
    notes = render_release_notes([], version="9.9.9")
    assert notes.startswith("# Transkryptor 9.9.9")


def test_whats_new_from_the_changelog_lands_under_its_heading() -> None:
    news = "- Nowa funkcja,\n  opisana w dwóch liniach."
    notes = render_release_notes([LINUX], whats_new=news)
    assert f"## Nowości w tej wersji\n\n{news}\n\n## Artefakty" in notes


def test_notes_without_news_skip_the_section() -> None:
    assert "## Nowości" not in render_release_notes([LINUX])
