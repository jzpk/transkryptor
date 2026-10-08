"""Testy spójności dokumentacji wydania z kodem budowania.

Dokumenty wydania powtarzają liczby i nazwy, które mają jedno źródło prawdy
w ``transkryptor.packaging.metadata``. Testy pilnują, żeby się nie rozjechały,
i żeby komplet wymagany przez fazę 05 w ogóle istniał.
"""

import pytest

from transkryptor.packaging import metadata
from transkryptor.packaging.metadata import REPO_ROOT

# Dokumenty wydania leżą w specs/docs, poza repozytorium (.gitignore) — w CI
# ich nie ma, więc testy treści są wtedy pomijane, a testy workflow zostają.
DOCS = REPO_ROOT / "specs" / "docs"
INSTALLATION = DOCS / "installation.md"
PRIVACY = DOCS / "privacy.md"
RELEASE_PROCESS = DOCS / "release-process.md"
LICENSES = DOCS / "licenses.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

# Lista kontrolna wydania z specs/delivery.md — każda pozycja musi zostać
# przeniesiona do instrukcji, z której korzysta wydawca.
DELIVERY_CHECKLIST = (
    "Instalator nie wymaga interpretera Python.",
    "Program uruchamia się bez modelu ASR.",
    "MP3 można otworzyć i odtworzyć.",
    "Eksport DOCX zachowuje tekst i indeksy górne.",
    "Po pobraniu modelu ASR przechodzi test offline.",
    "Licencje zależności oraz modelu są uwzględnione.",
    "Artefakty mają sumy kontrolne.",
)


needs_docs = pytest.mark.skipif(
    not DOCS.is_dir(), reason="brak specs/docs (poza repozytorium)"
)


@needs_docs
@pytest.mark.parametrize("document", [INSTALLATION, PRIVACY, RELEASE_PROCESS, LICENSES])
def test_release_documents_exist(document) -> None:
    assert document.is_file(), f"brak dokumentu wydania: {document.name}"


@needs_docs
def test_release_process_carries_the_delivery_checklist() -> None:
    text = RELEASE_PROCESS.read_text(encoding="utf-8")
    for item in DELIVERY_CHECKLIST:
        assert item in text, f"brak pozycji listy kontrolnej: {item}"


@needs_docs
def test_release_process_describes_the_offline_acceptance_test() -> None:
    """ACC-11 wymaga ręcznego potwierdzenia z odłączoną siecią."""
    text = RELEASE_PROCESS.read_text(encoding="utf-8")
    assert "ACC-11" in text
    assert "odłącz interfejs sieciowy" in text.lower()


@needs_docs
def test_release_process_explains_why_onedir_is_mandatory() -> None:
    text = RELEASE_PROCESS.read_text(encoding="utf-8")
    assert "onedir" in text
    assert "LGPL-3.0" in text


@needs_docs
def test_installation_repeats_the_hardware_requirements_verbatim() -> None:
    text = INSTALLATION.read_text(encoding="utf-8")
    for requirement in metadata.HARDWARE_REQUIREMENTS:
        assert (
            requirement.minimum in text
        ), f"wymaganie „{requirement.resource}” rozjechało się z metadata.py"


@needs_docs
def test_installation_states_the_supported_systems() -> None:
    text = INSTALLATION.read_text(encoding="utf-8")
    assert metadata.LINUX_GLIBC_BASELINE in text
    assert "Windows 10" in text
    assert "Python nie musi być zainstalowany" in text


@needs_docs
def test_installation_covers_model_download_and_limitations() -> None:
    text = INSTALLATION.read_text(encoding="utf-8")
    assert "Systran/faster-whisper-medium" in text
    assert "## Ograniczenia szkicu ASR" in text
    assert "--self-test" in text


@needs_docs
def test_privacy_document_states_the_only_network_call() -> None:
    text = PRIVACY.read_text(encoding="utf-8").lower()
    assert "nie zbiera telemetrii" in text
    assert "huggingface.co" in text
    assert "acc-11" in text


@needs_docs
def test_license_registry_has_no_open_risks_left() -> None:
    """Faza 05 miała zamknąć ryzyka licencyjne PySide6 i PyAV."""
    text = LICENSES.read_text(encoding="utf-8")
    assert "Otwarte ryzyko" not in text
    assert "libx264" in text
    assert "onedir" in text


def test_workflow_builds_both_platforms_natively() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "windows-latest" in text
    assert "ubuntu-22.04" in text
    assert "appimagetool" in text
    assert "innosetup" in text.lower()


def test_workflow_glibc_baseline_matches_the_runner() -> None:
    """Zmiana runnera Ubuntu zmienia najstarszą obsługiwaną glibc."""
    assert metadata.LINUX_BUILD_BASELINE.startswith("Ubuntu 22.04")
    assert "ubuntu-22.04" in WORKFLOW.read_text(encoding="utf-8")
