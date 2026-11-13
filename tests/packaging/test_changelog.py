"""Testy historii zmian: skąd noty wydania biorą nowości wersji."""

from datetime import date

import pytest

from transkryptor import __version__
from transkryptor.packaging import changelog
from transkryptor.packaging.changelog import ChangelogError

CHANGELOG = """\
# Historia zmian

Wstęp.

## 0.2.3 - 2026-10-09

- Poprzednia zmiana.
"""

NEWS = "- Nowa funkcja,\n  opisana w dwóch liniach."


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "CHANGELOG.md"
    target.write_text(CHANGELOG, encoding="utf-8")
    fragments = changelog.fragments_dir(target)
    fragments.mkdir()
    (fragments / "README.md").write_text("# Instrukcja\n", encoding="utf-8")
    (fragments / "b-feature.md").write_text(NEWS + "\n", encoding="utf-8")
    (fragments / "a-fix.md").write_text("- Poprawka.\n", encoding="utf-8")
    return target


def test_section_of_a_version_ignores_the_date_in_its_heading() -> None:
    assert changelog.section(CHANGELOG, "0.2.3") == "- Poprzednia zmiana."
    assert changelog.section(CHANGELOG, "0.2.2") is None


def test_unreleased_news_come_from_fragments_in_name_order(path) -> None:
    assert changelog.whats_new("0.2.4", path) == f"- Poprawka.\n\n{NEWS}"


def test_released_version_uses_its_own_section(path) -> None:
    assert changelog.whats_new("0.2.3", path) == "- Poprzednia zmiana."


def test_no_fragments_and_no_version_section_fails(tmp_path) -> None:
    target = tmp_path / "CHANGELOG.md"
    target.write_text(CHANGELOG, encoding="utf-8")
    with pytest.raises(ChangelogError, match="0.2.4"):
        changelog.whats_new("0.2.4", target)


def test_missing_file_is_reported(tmp_path) -> None:
    with pytest.raises(ChangelogError, match="Brak pliku"):
        changelog.whats_new("0.2.4", tmp_path / "CHANGELOG.md")


def test_release_puts_fragments_into_a_dated_section_above_older_ones(path) -> None:
    changelog.release("0.2.4", date(2026, 10, 10), path)

    text = path.read_text(encoding="utf-8")
    assert changelog.section(text, "0.2.4") == f"- Poprawka.\n\n{NEWS}"
    assert text.index("Wstęp.") < text.index("## 0.2.4 - 2026-10-10")
    assert text.index("## 0.2.4") < text.index("## 0.2.3")
    assert changelog.section(text, "0.2.3") == "- Poprzednia zmiana."
    remaining = sorted(p.name for p in changelog.fragments_dir(path).iterdir())
    assert remaining == ["README.md"]


def test_release_refuses_when_there_are_no_fragments(path) -> None:
    changelog.release("0.2.4", path=path)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ChangelogError, match="Brak fragmentów"):
        changelog.release("0.2.5", path=path)
    assert path.read_text(encoding="utf-8") == before


def test_release_refuses_an_existing_version(path) -> None:
    with pytest.raises(ChangelogError, match="ma już sekcję"):
        changelog.release("0.2.3", path=path)
    assert len(list(changelog.fragments_dir(path).glob("*.md"))) == 3


def test_cli_check_fails_for_a_version_without_section(path, capsys) -> None:
    assert changelog.main(["check", "0.2.3", "--file", str(path)]) == 0
    assert changelog.main(["check", "0.2.4", "--file", str(path)]) == 1
    assert "::error::" in capsys.readouterr().err


def test_project_changelog_describes_the_current_version() -> None:
    """Budowanie bieżącej wersji musi mieć z czego złożyć nowości."""
    assert changelog.whats_new(__version__)
