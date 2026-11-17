"""Testy danych programu dla strony projektu (kontrakt z repozytorium strony)."""

import json

import pytest

from transkryptor import __version__
from transkryptor.packaging import site_data
from transkryptor.packaging.changelog import CHANGELOG_FILE
from transkryptor.packaging.metadata import HARDWARE_REQUIREMENTS, targets
from transkryptor.packaging.site_data import SiteDataError

CHANGELOG = """\
# Historia zmian

Wstęp.

## 0.2.4 - 2026-10-11

- Nowa funkcja,
  opisana w **dwóch** liniach.

## 0.2.3 - 2026-10-09

- Poprzednia zmiana.
"""


def test_released_sections_skip_unreleased_and_keep_order() -> None:
    releases = site_data.released_sections(CHANGELOG)

    assert [release.version for release in releases] == ["0.2.4", "0.2.3"]
    assert releases[0].date == "2026-10-11"
    assert releases[1].body == "- Poprzednia zmiana."


def test_section_without_date_has_no_date() -> None:
    (release,) = site_data.released_sections("## 0.1.0\n\n- x\n")
    assert release.date is None


def test_data_describe_the_latest_release() -> None:
    data = site_data.site_data(CHANGELOG, version="0.2.4")

    assert data["schema"] == site_data.SCHEMA
    assert data["version"] == "0.2.4"
    assert data["releases"] == [
        {
            "version": "0.2.4",
            "date": "2026-10-11",
            "body": "- Nowa funkcja,\n  opisana w **dwóch** liniach.",
        },
        {"version": "0.2.3", "date": "2026-10-09", "body": "- Poprzednia zmiana."},
    ]
    downloads = data["downloads"]
    assert isinstance(downloads, dict)
    for key, target in targets("0.2.4").items():
        assert downloads[key]["file"] == target.artifact_name
        assert downloads[key]["display_name"] == target.display_name
    requirements = data["requirements"]
    assert isinstance(requirements, list)
    assert [item["resource"] for item in requirements] == [
        item.resource for item in HARDWARE_REQUIREMENTS
    ]


def test_data_refuse_a_changelog_behind_the_program() -> None:
    with pytest.raises(SiteDataError, match="0.2.4"):
        site_data.site_data(CHANGELOG, version="0.2.5")


def test_data_refuse_a_changelog_without_releases() -> None:
    with pytest.raises(SiteDataError, match="wydanej"):
        site_data.site_data("# Historia zmian\n\nWstęp.\n", version="0.1.0")


def test_repository_changelog_matches_the_program_version(tmp_path, capsys) -> None:
    out = tmp_path / "site-data.json"

    assert site_data.main(["--out", str(out)]) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == __version__
    assert str(out) in capsys.readouterr().out


def test_cli_reports_a_missing_changelog(tmp_path, capsys) -> None:
    missing = tmp_path / CHANGELOG_FILE.name
    out = tmp_path / "site-data.json"

    assert site_data.main(["--out", str(out), "--changelog", str(missing)]) == 1

    assert "::error::" in capsys.readouterr().err
    assert not out.exists()
