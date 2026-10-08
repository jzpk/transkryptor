"""Testy tożsamości wydania: nazwy artefaktów i wymagania sprzętowe."""

import pytest

from transkryptor import __version__
from transkryptor.packaging import metadata


def test_artifact_names_carry_version_and_platform() -> None:
    available = metadata.targets("1.2.3")
    assert available["windows"].artifact_name == (
        "Transkryptor-1.2.3-windows-x64-setup.exe"
    )
    assert available["linux"].artifact_name == "Transkryptor-1.2.3-x86_64.AppImage"


def test_default_version_follows_application() -> None:
    assert metadata.VERSION == __version__
    for target in metadata.targets().values():
        assert __version__ in target.artifact_name


def test_unknown_target_names_available_options() -> None:
    with pytest.raises(KeyError) as error:
        metadata.target_for("macos")
    assert "windows" in str(error.value)
    assert "linux" in str(error.value)


def test_hardware_requirements_cover_release_documentation() -> None:
    resources = {requirement.resource for requirement in metadata.HARDWARE_REQUIREMENTS}
    assert {"RAM", "Dysk", "CPU", "Sieć"} <= resources
    for requirement in metadata.HARDWARE_REQUIREMENTS:
        assert requirement.minimum
        assert requirement.basis, f"brak podstawy liczby dla {requirement.resource}"


def test_cpu_requirement_is_marked_as_recommendation() -> None:
    """Pomiar z fazy 04 nie objął maszyny czterordzeniowej (docs/benchmarks-asr.md)."""
    cpu = next(
        requirement
        for requirement in metadata.HARDWARE_REQUIREMENTS
        if requirement.resource == "CPU"
    )
    assert "rekomendacja" in cpu.basis


def test_windows_app_guid_is_plain_guid() -> None:
    """Klamry dokłada szablon instalatora; stała trzyma sam identyfikator."""
    assert "{" not in metadata.WINDOWS_APP_GUID
    assert len(metadata.WINDOWS_APP_GUID) == 36


def test_pyinstaller_spec_exists_in_repository() -> None:
    assert metadata.PYINSTALLER_SPEC.is_file()
    assert (metadata.REPO_ROOT / "LICENSE").is_file()


def test_icons_are_shipped_with_the_packaging_module() -> None:
    assert metadata.ICON_PNG.is_file()
    assert metadata.ICON_ICO.is_file()
    # Sygnatura ICO: zarezerwowane 0, typ 1 (ikona).
    assert metadata.ICON_ICO.read_bytes()[:4] == b"\x00\x00\x01\x00"
