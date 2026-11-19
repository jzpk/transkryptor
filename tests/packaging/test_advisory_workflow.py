"""Testy workflow „Ostrzeżenie bezpieczeństwa” (``advisory.yml``).

Ten sam łańcuch zaufania co w workflow wydania: klucz podpisu widzi tylko
minisign z przypiętą sumą, a publikacja sprawdza podpis kodem aplikacji.
"""

import re

from transkryptor.packaging.metadata import REPO_ROOT
from transkryptor.update.advisory import ADVISORY_ASSET, ADVISORY_TAG

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ADVISORY = WORKFLOWS / "advisory.yml"


def _job(text: str, name: str) -> str:
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S)
    assert match, f"brak joba {name}"
    return match.group(1)


def test_signing_job_runs_no_repository_or_python_dependency_code() -> None:
    text = ADVISORY.read_text(encoding="utf-8")
    signing = _job(text, "podpis")
    assert "environment: Release" in signing
    assert "secrets.MINISIGN_SECRET_KEY" in signing
    for forbidden in ("actions/checkout", "setup-uv", "uv ", "python"):
        assert forbidden not in signing, forbidden
    assert text.count("MINISIGN_SECRET_KEY: ${{ secrets") == 1


def test_signing_job_accepts_only_advisory_comments() -> None:
    from transkryptor.update.signature import advisory_comment_for

    signing = _job(ADVISORY.read_text(encoding="utf-8"), "podpis")
    pattern = re.search(r"grep -Eq '(\^transkryptor advisory [^']+)'", signing)
    assert pattern
    assert re.fullmatch(pattern.group(1), advisory_comment_for(12))
    assert not re.fullmatch(pattern.group(1), "transkryptor 1.0.0 SHA256SUMS.txt")


def test_publication_verifies_before_upload_to_a_prerelease() -> None:
    publish = _job(ADVISORY.read_text(encoding="utf-8"), "publikacja")
    verify = publish.index("python -m transkryptor.update.advisory verify")
    assert verify < publish.index("gh release upload")
    assert "--prerelease --latest=false" in publish
    assert f"ADVISORY_TAG: {ADVISORY_TAG}" in ADVISORY.read_text(encoding="utf-8")
    assert f"dist/{ADVISORY_ASSET}" in publish


def test_advisory_tag_does_not_trigger_the_release_workflow() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    tags = re.search(r"tags:\n((?:\s+- .+\n)+)", release)
    assert tags
    patterns = re.findall(r'- "([^"]+)"', tags.group(1))
    assert patterns and all(p.startswith("v") for p in patterns)
    assert not ADVISORY_TAG.startswith("v")


def test_minisign_is_pinned_like_in_the_release_workflow() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    text = ADVISORY.read_text(encoding="utf-8")
    for name in ("MINISIGN_VERSION", "MINISIGN_SHA256"):
        line = re.search(rf"^  {name}: .+$", release, re.M)
        assert line and line.group(0) in text, name


def test_checkouts_do_not_persist_tokens() -> None:
    text = ADVISORY.read_text(encoding="utf-8")
    assert text.count("actions/checkout") == text.count("persist-credentials: false")


def test_user_input_reaches_shell_only_through_environment() -> None:
    """``${{ inputs.* }}`` w ``run:`` pozwoliłoby wstrzyknąć polecenie."""
    for block in re.findall(r"run: \|\n((?:\s{10,}.*\n|\n)+)", ADVISORY.read_text()):
        assert "${{" not in block
