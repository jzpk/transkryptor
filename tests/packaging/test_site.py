"""Testy strony projektu: historia zmian, linki pobierania i składanie strony."""

import json
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

## 0.2.4 - 2026-10-11

- Nowa funkcja,
  opisana w **dwóch** liniach.
- Skrót `Ctrl+<` działa.

## 0.2.3 - 2026-10-09

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


def test_build_adds_the_display_switches_to_every_page(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    assert (out / "site.js").is_file()
    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        assert re.search(r'<script src="/?site.js"></script>', page)
        assert 'class="icon-button theme-toggle"' in page
        assert 'class="motion-switch"' in page
        assert 'role="switch"' in page


def test_every_page_links_the_faq_and_has_link_previews(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        assert re.search(r'href="/?faq.html"', page)
        if name == "404.html":
            continue
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page)
        assert canonical is not None
        assert canonical[1].startswith(site.SITE_URL + "/")
        assert f'<meta property="og:url" content="{canonical[1]}" />' in page
        image = re.search(r'<meta property="og:image" content="([^"]+)"', page)
        assert image is not None
        assert image[1].startswith(site.SITE_URL + "/")
        assert (out / image[1].removeprefix(site.SITE_URL + "/")).is_file()


def test_faq_questions_have_unique_anchors(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = (out / "faq.html").read_text(encoding="utf-8")
    anchors = re.findall(r'<details class="faq-item" id="([^"]+)"', page)
    assert "smartscreen" in anchors
    assert len(anchors) == len(set(anchors))
    for link in re.findall(r'href="#([^"]+)"', page):
        assert link in anchors


def test_background_letters_are_polish_and_reproducible() -> None:
    layer, css = site.background_letters()

    letters = re.findall(r'<span style="[^"]*">(.)</span>', layer)
    assert len(letters) == site.LETTER_COUNT
    assert set(letters) <= set(site.LETTERS)
    assert (layer, css) == site.background_letters()
    assert layer.startswith('<div class="letters" aria-hidden="true">')
    # Klatki ze stałymi wartościami, bez var() - animacja zostaje na GPU.
    assert css.count("@keyframes litera-") == site.LETTER_COUNT
    assert "var(" not in css
    # Skrót „animation:” w stylu inline nadpisałby wstrzymanie animacji.
    assert "animation:" not in layer


def test_build_adds_background_letters_to_every_page(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        assert '<div class="letters" aria-hidden="true">' in page
        assert "@keyframes litera-0{" in page


def test_changelog_releases_start_collapsed(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    index = site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = index.read_text(encoding="utf-8")
    assert page.count('<details class="release"') == 2
    assert " open>" not in page
    assert 'data-toggle-all="#zmiany .changelog"' in page


def test_pages_reference_only_existing_local_files(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        paths = [
            link.split("#")[0]
            for link in re.findall(r'(?:href|src)="([^"]+)"', page)
            if ":" not in link
        ]
        for srcset in re.findall(r'srcset="([^"]+)"', page):
            paths += [entry.split()[0] for entry in srcset.split(",") if entry.strip()]
        for path in paths:
            if path.strip("/"):
                assert (out / path.lstrip("/")).is_file(), f"{name}: {path}"


def test_not_found_page_uses_absolute_paths(changelog_file, tmp_path) -> None:
    """404 bywa pokazywana pod zagnieżdżonym adresem, np. /a/b/c."""
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = (out / "404.html").read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex" />' in page
    assert 'rel="canonical"' not in page
    for path in re.findall(r'(?:href|src)="([^"]+)"', page):
        assert path.startswith(("/", "https://", "#")), path


def test_download_cards_name_their_system(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    index = site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = index.read_text(encoding="utf-8")
    for key, target in targets("0.2.4").items():
        card = re.search(rf'<a class="download" href="([^"]+)" data-os="{key}"', page)
        assert card is not None
        assert card[1].endswith(target.artifact_name)
    assert re.search(r'data-download-for-os\s+data-version="0.2.4"', page)


def _json_ld(page: str) -> list[dict]:
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL
    )
    return [json.loads(block) for block in blocks]


def test_sitemap_lists_canonical_urls_of_indexed_pages(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    sitemap = (out / site.SITEMAP_FILE).read_text(encoding="utf-8")
    locations = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    canonicals = []
    for name in site.INDEXED_FILES:
        page = (out / name).read_text(encoding="utf-8")
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page)
        assert canonical is not None
        canonicals.append(canonical[1])
    assert locations == canonicals
    assert sitemap.count("<lastmod>2026-10-11</lastmod>") == len(locations)
    assert "404" not in sitemap


def test_robots_allows_crawling_and_points_to_the_sitemap(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    robots = (out / site.ROBOTS_FILE).read_text(encoding="utf-8")
    assert "Disallow" not in robots
    assert f"Sitemap: {site.SITE_URL}/{site.SITEMAP_FILE}" in robots


def test_home_page_describes_the_program_for_search_engines(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    index = site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    (data,) = _json_ld(index.read_text(encoding="utf-8"))
    types = {node["@type"]: node for node in data["@graph"]}
    program = types["SoftwareApplication"]
    assert program["softwareVersion"] == "0.2.4"
    assert program["datePublished"] == "2026-10-11"
    assert program["offers"]["price"] == "0"
    download = "https://github.com/owner/repo/releases/download/v0.2.4"
    assert program["downloadUrl"] == [
        f"{download}/{target.artifact_name}" for target in targets("0.2.4").values()
    ]
    assert types["WebSite"]["url"] == f"{site.SITE_URL}/"
    for url in (program["screenshot"], program["image"]):
        assert (out / url.removeprefix(site.SITE_URL + "/")).is_file()


def test_faq_structured_data_follows_the_questions_on_the_page(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = (out / "faq.html").read_text(encoding="utf-8")
    (data,) = _json_ld(page)
    assert data["@type"] == "FAQPage"
    questions = data["mainEntity"]
    assert len(questions) == page.count('<details class="faq-item"')
    for question in questions:
        text = question["name"] + question["acceptedAnswer"]["text"]
        assert question["name"] and question["acceptedAnswer"]["text"]
        assert "<" not in text and "&" not in text and "  " not in text
    assert "Czy Transkryptor jest płatny?" in [q["name"] for q in questions]


def test_author_page_has_a_profile_and_404_has_no_structured_data(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    (profile,) = _json_ld((out / "autor.html").read_text(encoding="utf-8"))
    assert profile["@type"] == "ProfilePage"
    assert profile["mainEntity"]["name"] == site.AUTHOR_NAME
    assert site.LINKEDIN_URL in profile["mainEntity"]["sameAs"]
    assert _json_ld((out / "404.html").read_text(encoding="utf-8")) == []


def test_structured_data_cannot_close_its_script_tag() -> None:
    page = site.add_structured_data("<head>\n  </head>", {"text": "</script><b>"})
    assert page.count("</script>") == 1
    (data,) = _json_ld(page)
    assert data == {"text": "</script><b>"}


def test_report_form_gets_the_worker_address_and_captcha_key(
    changelog_file, tmp_path
) -> None:
    out = tmp_path / "site"
    site.build(
        out,
        changelog_file,
        repo="owner/repo",
        expected_version="0.2.4",
        report_endpoint="https://zgloszenia.example.workers.dev",
        turnstile_site_key="0x4AAA&key",
    )

    page = (out / "zglos.html").read_text(encoding="utf-8")
    assert 'data-endpoint="https://zgloszenia.example.workers.dev"' in page
    assert 'data-sitekey="0x4AAA&amp;key"' in page
    # Bez skryptu albo bez Workera zostaje odnośnik do GitHuba.
    assert 'href="https://github.com/owner/repo/issues"' in page
    assert "zglos.html" in (out / site.SITEMAP_FILE).read_text(encoding="utf-8")


def test_report_form_configuration_comes_from_the_environment(
    changelog_file, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(site.REPORT_ENDPOINT_ENV, " https://worker.example ")
    monkeypatch.setenv(site.TURNSTILE_SITE_KEY_ENV, "klucz")
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    page = (out / "zglos.html").read_text(encoding="utf-8")
    assert 'data-endpoint="https://worker.example"' in page
    assert 'data-sitekey="klucz"' in page


def test_report_form_without_worker_has_an_empty_endpoint(
    changelog_file, tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv(site.REPORT_ENDPOINT_ENV, raising=False)
    monkeypatch.delenv(site.TURNSTILE_SITE_KEY_ENV, raising=False)
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    assert 'data-endpoint=""' in (out / "zglos.html").read_text(encoding="utf-8")


def test_report_form_refuses_an_insecure_worker_address(
    changelog_file, tmp_path
) -> None:
    with pytest.raises(SiteError, match="https://"):
        site.build(
            tmp_path / "site",
            changelog_file,
            repo="owner/repo",
            expected_version="0.2.4",
            report_endpoint="http://worker.example",
        )


def test_every_page_footer_links_the_report_form(changelog_file, tmp_path) -> None:
    out = tmp_path / "site"
    site.build(out, changelog_file, repo="owner/repo", expected_version="0.2.4")

    for name in site.TEMPLATE_FILES:
        page = (out / name).read_text(encoding="utf-8")
        assert re.search(r'<a href="/?zglos.html">Zgłoś problem lub pomysł</a>', page)
