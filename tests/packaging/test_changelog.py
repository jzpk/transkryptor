"""Testy historii zmian: skąd noty wydania biorą nowości wersji."""

from datetime import date

import pytest

from transkryptor import __version__
from transkryptor.packaging import changelog
from transkryptor.packaging.changelog import ChangelogError

CHANGELOG = """\
# Historia zmian

Wstęp.

## Nieopublikowane

- Nowa funkcja,
  opisana w dwóch liniach.

## 0.2.3 — 2026-10-09

- Poprzednia zmiana.
"""


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "CHANGELOG.md"
    target.write_text(CHANGELOG, encoding="utf-8")
    return target


def test_section_of_a_version_ignores_the_date_in_its_heading() -> None:
    assert changelog.section(CHANGELOG, "0.2.3") == "- Poprzednia zmiana."
    assert changelog.section(CHANGELOG, "0.2.2") is None


def test_multiline_entries_are_kept_verbatim(path) -> None:
    assert changelog.whats_new("0.2.4", path) == (
        "- Nowa funkcja,\n  opisana w dwóch liniach."
    )


def test_released_version_uses_its_own_section(path) -> None:
    assert changelog.whats_new("0.2.3", path) == "- Poprzednia zmiana."


def test_empty_unreleased_section_without_version_section_fails(path) -> None:
    path.write_text("## Nieopublikowane\n\n## 0.2.3\n\n- x\n", encoding="utf-8")
    with pytest.raises(ChangelogError, match="0.2.4"):
        changelog.whats_new("0.2.4", path)


def test_missing_file_is_reported(tmp_path) -> None:
    with pytest.raises(ChangelogError, match="Brak pliku"):
        changelog.whats_new("0.2.4", tmp_path / "CHANGELOG.md")


def test_release_turns_unreleased_into_a_dated_version_section(path) -> None:
    changelog.release("0.2.4", date(2026, 10, 10), path)

    text = path.read_text(encoding="utf-8")
    assert changelog.section(text, changelog.UNRELEASED) == ""
    assert changelog.section(text, "0.2.4") == (
        "- Nowa funkcja,\n  opisana w dwóch liniach."
    )
    assert "## 0.2.4 — 2026-10-10" in text
    assert text.index("## Nieopublikowane") < text.index("## 0.2.4")
    assert changelog.section(text, "0.2.3") == "- Poprzednia zmiana."


def test_release_refuses_an_empty_unreleased_section(path) -> None:
    changelog.release("0.2.4", path=path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ChangelogError, match="pusta"):
        changelog.release("0.2.5", path=path)
    assert path.read_text(encoding="utf-8") == before


def test_release_refuses_an_existing_version(path) -> None:
    with pytest.raises(ChangelogError, match="ma już sekcję"):
        changelog.release("0.2.3", path=path)


def test_cli_check_fails_for_a_version_without_section(path, capsys) -> None:
    assert changelog.main(["check", "0.2.3", "--file", str(path)]) == 0
    assert changelog.main(["check", "0.2.4", "--file", str(path)]) == 1
    assert "::error::" in capsys.readouterr().err


def test_project_changelog_describes_the_current_version() -> None:
    """Budowanie bieżącej wersji musi mieć z czego złożyć nowości."""
    assert changelog.whats_new(__version__)
