"""Testy strony projektu: historia zmian, linki pobierania i składanie strony."""

import re

import pytest

from transkryptor import __version__
from transkryptor.packaging import site
from transkryptor.packaging.metadata import targets
from transkryptor.packaging.site import SiteError

CHANGELOG = """\
# Historia zmian

Wstęp.

## Nieopublikowane

- Funkcja w toku.

## 0.2.4 — 2026-10-11

- Nowa funkcja,
  opisana w **dwóch** liniach.
- Skrót `Ctrl+<` działa.

## 0.2.3 — 2026-10-09

- Poprzednia zmiana.
"""


@pytest.fixture
def changelog_file(tmp_path):
    target = tmp_path / "CHANGELOG.md"
    target.write_text(CHANGELOG, encoding="utf-8")
    return target


def test_released_sections_skip_unreleased_and_keep_order() -> None:
    releases = site.released_sections(CHANGELOG)

    assert [release.version for release in releases] == ["0.2.4", "0.2.3"]
    assert releases[0].date == "2026-10-11"
    assert releases[1].body == "- Poprzednia zmiana."


def test_section_without_date_has_no_date() -> None:
    (release,) = site.released_sections("## 0.1.0\n\n- x\n")
    assert release.date is None


def test_date_is_written_in_polish() -> None:
    assert site.format_date("2026-10-18") == "18 października 2026"


def test_markdown_list_joins_continuation_lines_and_formats_inline() -> None:
    body = site.released_sections(CHANGELOG)[0].body

    assert site.render_markdown(body) == (
        "<ul><li>Nowa funkcja, opisana w <strong>dwóch</strong> liniach.</li>"
        "<li>Skrót <code>Ctrl+&lt;</code> działa.</li></ul>"
    )


def test_markdown_code_is_not_formatted_and_text_is_escaped() -> None:
    assert site.render_markdown("Akapit <b>\n`**x**` i **y**") == (
        "<p>Akapit &lt;b&gt; <code>**x**</code> i <strong>y</strong></p>"
    )


def test_build_links_downloads_of_the_latest_release(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    index = site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = index.read_text(encoding="utf-8")
    download = "https://github.com/owner/repo/releases/download/v0.2.4"
    for target in targets("0.2.4").values():
        assert f'href="{download}/{target.artifact_name}"' in page
    assert "SHA256SUMS.txt" not in page
    assert 'id="v0.2.3"' in page
    assert "Funkcja w toku" not in page
    assert (out / "style.css").is_file()
    assert (out / "icon.png").is_file()
    assert any((out / "img").iterdir())


def test_build_refuses_a_changelog_behind_the_program(changelog_file, tmp_path) -> None:
    with pytest.raises(SiteError, match="0.2.4"):
        site.build(tmp_path, changelog_file, expected_version="0.2.5")


def test_build_refuses_a_changelog_without_releases(tmp_path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("## Nieopublikowane\n\n- x\n", encoding="utf-8")
    with pytest.raises(SiteError, match="wydanej"):
        site.build(tmp_path / "site", path)


def test_project_site_builds_for_the_current_version(tmp_path) -> None:
    """Strona z repozytorium: najnowsza wydana wersja to wersja programu."""
    page = site.build(tmp_path).read_text(encoding="utf-8")
    assert f"Pobierz wersję {__version__}" in page


def test_build_adds_the_author_page_linked_from_the_header(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    index = site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    author = (out / "autor.html").read_text(encoding="utf-8")
    assert site.AUTHOR_NAME in author
    assert f'href="{site.LINKEDIN_URL}"' in author
    assert 'href="https://github.com/owner"' in author
    assert 'href="autor.html"' in index.read_text(encoding="utf-8")
    assert (out / "img" / "autor.jpg").is_file()
    assert (out / "img" / "ikony.svg").is_file()


def test_build_adds_the_theme_toggle_to_every_page(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    assert (out / "theme.js").is_file()
    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        assert '<script src="theme.js"></script>' in page
        assert 'class="icon-button theme-toggle"' in page


def test_background_letters_are_polish_and_reproducible() -> None:
    layer = site.letters_html()

    letters = re.findall(r'<span style="[^"]*">(.)</span>', layer)
    assert len(letters) == site.LETTER_COUNT
    assert set(letters) <= set(site.LETTERS)
    assert layer == site.letters_html()
    assert layer.startswith('<div class="letters" aria-hidden="true">')


def test_build_adds_background_letters_to_every_page(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        assert '<div class="letters" aria-hidden="true">' in page
