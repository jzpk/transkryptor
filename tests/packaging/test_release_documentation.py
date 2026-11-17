"""Testy spójności workflow wydania z kodem budowania.

Workflow powtarza liczby i nazwy, które mają jedno źródło prawdy
w ``transkryptor.packaging.metadata``. Testy pilnują, żeby się nie rozjechały.
"""

import re

from transkryptor.packaging import metadata
from transkryptor.packaging.metadata import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def test_workflow_builds_both_platforms_natively() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "windows-2022" in text
    assert "ubuntu-22.04" in text
    assert "appimagetool" in text
    assert "innosetup" in text.lower()


def test_workflows_pin_actions_to_commit_shas() -> None:
    """Tag akcji można przesunąć; SHA commitu - nie (SEC-04)."""
    for workflow in WORKFLOW.parent.glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" in line:
                # Workflow z tego repozytorium idzie z tym samym commitem.
                if line.split("uses:", 1)[1].strip().startswith("./"):
                    continue
                ref = line.split("@", 1)[1].split()[0]
                assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{workflow.name}: {line}"


def test_downloaded_tools_are_pinned_to_the_same_checksums() -> None:
    """Workflow i Dockerfile'e pobierają te same wersje z tymi samymi sumami."""
    text = WORKFLOW.read_text(encoding="utf-8")
    docker = REPO_ROOT / "packaging" / "docker"
    pairs = {
        "APPIMAGETOOL": docker / "linux.Dockerfile",
        "INNO_SETUP": docker / "windows.Dockerfile",
    }
    for tool, dockerfile in pairs.items():
        sha = re.search(rf"{tool}_SHA256: ([0-9a-f]{{64}})", text)
        version = re.search(rf'{tool}_VERSION: "([^"]+)"', text)
        assert sha and version, tool
        recipe = dockerfile.read_text(encoding="utf-8")
        assert f"{tool}_SHA256={sha.group(1)}" in recipe
        assert f"{tool}_VERSION={version.group(1)}" in recipe
    assert "continuous" not in text


def test_release_is_signed_and_verified_before_publication() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 -m transkryptor.update.keys" in text
    assert "environment: Release" in text
    assert "SHA256SUMS.txt.minisig" in text
    sign = text.index('minisign" -S')
    verify = text.index("python -m transkryptor.update.signature")
    publish = text.index("gh release create")
    assert sign < verify < publish


def test_workflow_glibc_baseline_matches_the_runner() -> None:
    """Zmiana runnera Ubuntu zmienia najstarszą obsługiwaną glibc."""
    assert metadata.LINUX_BUILD_BASELINE.startswith("Ubuntu 22.04")
    assert "ubuntu-22.04" in WORKFLOW.read_text(encoding="utf-8")


def test_windows_self_test_does_not_wait_for_the_whole_process_tree() -> None:
    """Start-Process -Wait czeka też na program uruchomiony przez instalator.

    Cicha instalacja startuje okno aplikacji (WizardSilent), które samo się
    nie zamyka - z -Wait krok wydania 0.3.0 wisiał do anulowania.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text.split("- name: Instalacja i --self-test", 1)[1].split("- uses:", 1)[0]
    assert "-Wait" not in step
    assert "WaitForExit(" in step
    assert "timeout-minutes:" in step


def test_manual_release_builds_in_one_run_without_retriggering_ci() -> None:
    """Commit wydania nie uruchamia CI ani drugiego przebiegu „Wydanie”.

    Przebieg ręczny sam buduje i publikuje, więc joby budowania nie mogą
    czekać na przebieg z push taga, a commit musi mieć [skip ci].
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'git commit -am "Wydanie v$VERSION" -m "[skip ci]"' in text
    assert "outputs.publish" not in text


def _job(text: str, name: str) -> str:
    """Treść joba ``name`` z workflow (do następnego joba najwyższego poziomu)."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S)
    assert match, f"brak joba {name}"
    return match.group(1)


def test_signing_job_runs_no_repository_or_python_dependency_code() -> None:
    """Klucz podpisu widzi tylko minisign z przypiętą sumą.

    Kod uruchomiony w tym samym jobie (zależność z uv.lock, kod repozytorium)
    mógłby przechwycić klucz i podpisywać złośliwe aktualizacje.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    signing = _job(text, "podpis")
    assert "environment: Release" in signing
    assert "secrets.MINISIGN_SECRET_KEY" in signing
    for forbidden in ("actions/checkout", "setup-uv", "uv ", "python"):
        assert forbidden not in signing, forbidden
    assert text.count("environment: Release") == 1
    assert text.count("MINISIGN_SECRET_KEY: ${{ secrets") == 1


def test_signing_job_uses_the_application_trusted_comment() -> None:
    from transkryptor.update.signature import trusted_comment_for

    signing = _job(WORKFLOW.read_text(encoding="utf-8"), "podpis")
    expected = trusted_comment_for("$VERSION")
    assert f'COMMENT="{expected}"' in signing


def test_checkouts_do_not_persist_tokens_outside_the_release_push() -> None:
    """Token zostaje w .git/config tylko w jobach, które pushują.

    ``wersja`` pushuje commit wydania i tag, ``scalenie`` - scalenie gałęzi
    wydania do main (sam git, bez kodu repozytorium).
    """
    for workflow in WORKFLOW.parent.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for match in re.finditer(r"^  ([\w-]+):\n", text, re.M):
            job = _job(text, match.group(1))
            if "actions/checkout" not in job:
                continue
            step = job.split("actions/checkout", 1)[1].split("- name:", 1)[0]
            if workflow == WORKFLOW and match.group(1) in ("wersja", "scalenie"):
                assert "secrets.RELEASE_PAT" in step
                continue
            assert (
                "persist-credentials: false" in step
            ), f"{workflow.name}: {match.group(1)}"


def test_release_runs_only_end_to_end_tests_and_ci_only_unit_tests() -> None:
    """Testy jednostkowe biegną w CI, a bramka wydania to testy e2e."""
    release = WORKFLOW.read_text(encoding="utf-8")
    gate = _job(release, "e2e")
    assert "uv run pytest --e2e tests/e2e" in gate
    assert release.count("pytest") == 1
    assert "needs: e2e" in _job(release, "wersja")

    ci = (WORKFLOW.parent / "ci.yml").read_text(encoding="utf-8")
    assert "uv run pytest" in ci
    assert "--e2e" not in ci
