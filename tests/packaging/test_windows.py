"""Testy generowania instalatora Windows (Inno Setup)."""

from pathlib import Path

import pytest

from transkryptor.packaging import windows
from transkryptor.packaging.metadata import WINDOWS_APP_GUID

DIST = Path(r"C:\build\dist\transkryptor")
OUTPUT = Path(r"C:\out")
LICENSE = Path(r"C:\build\dist\transkryptor\licenses\LICENSE")
ARTIFACT = "Transkryptor-0.1.0-windows-x64-setup.exe"


def render() -> str:
    return windows.render_iss(
        DIST, OUTPUT, artifact_name=ARTIFACT, license_file=LICENSE
    )


def test_app_id_uses_inno_setup_brace_escaping() -> None:
    """W składni Inno Setup „{{” to pojedynczy znak „{”."""
    assert f"AppId={{{{{WINDOWS_APP_GUID}}}" in render()


def test_output_base_filename_has_no_extension() -> None:
    """Inno Setup sam dokłada „.exe” — inaczej powstałby plik z podwójnym."""
    script = render()
    assert "OutputBaseFilename=Transkryptor-0.1.0-windows-x64-setup\n" in script
    assert ".exe.exe" not in script


def test_installer_copies_the_whole_onedir_tree() -> None:
    script = render()
    assert "recursesubdirs" in script
    assert f'Source: "{DIST}\\*"' in script


def test_installer_shows_the_application_license() -> None:
    assert f"LicenseFile={LICENSE}" in render()


def test_installer_does_not_require_administrator() -> None:
    script = render()
    assert "PrivilegesRequired=lowest" in script
    assert "PrivilegesRequiredOverridesAllowed=dialog" in script


def test_installer_targets_64_bit_only() -> None:
    assert "ArchitecturesAllowed=x64compatible" in render()


def test_script_is_written_where_requested(tmp_path) -> None:
    script = windows.write_iss(
        DIST,
        OUTPUT,
        tmp_path / "generated" / "transkryptor.iss",
        artifact_name=ARTIFACT,
        license_file=LICENSE,
    )
    assert script.is_file()
    assert "[Setup]" in script.read_text(encoding="utf-8")


def test_explicit_compiler_path_wins() -> None:
    assert windows.find_iscc(r"D:\InnoSetup\ISCC.exe") == r"D:\InnoSetup\ISCC.exe"


def test_build_without_a_compiler_explains_what_to_install(tmp_path) -> None:
    with pytest.raises(FileNotFoundError) as error:
        windows.build(
            tmp_path,
            tmp_path / "out",
            artifact_name=ARTIFACT,
            license_file=LICENSE,
            tool=None,
        )
    assert "Inno Setup" in str(error.value)


def test_build_invokes_the_compiler_with_the_generated_script(tmp_path) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def runner(command, **_kwargs):
        calls.append(command)
        (tmp_path / "out").mkdir(exist_ok=True)
        (tmp_path / "out" / ARTIFACT).write_bytes(b"setup")
        return Result()

    artifact = windows.build(
        tmp_path,
        tmp_path / "out",
        artifact_name=ARTIFACT,
        license_file=LICENSE,
        work_dir=tmp_path,
        tool="ISCC.exe",
        runner=runner,
    )
    assert artifact.is_file()
    assert calls[0][0] == "ISCC.exe"
    assert calls[0][1].endswith(windows.SCRIPT_NAME)


def test_failed_compilation_is_reported(tmp_path) -> None:
    class Result:
        returncode = 1

    with pytest.raises(RuntimeError) as error:
        windows.build(
            tmp_path,
            tmp_path / "out",
            artifact_name=ARTIFACT,
            license_file=LICENSE,
            work_dir=tmp_path,
            tool="ISCC.exe",
            runner=lambda *_args, **_kwargs: Result(),
        )
    assert "kodem 1" in str(error.value)


def test_uninstaller_removes_user_settings() -> None:
    """Deinstalacja usuwa ustawienia z rejestru, ale instalator ich nie tworzy."""
    from transkryptor.ui.settings_store import SETTINGS_ORGANIZATION

    script = render()
    assert windows.SETTINGS_REGISTRY_KEY == SETTINGS_ORGANIZATION
    assert (
        'Root: HKCU; Subkey: "Software\\transkryptor"; '
        "Flags: uninsdeletekey dontcreatekey" in script
    )


def test_silent_update_restarts_the_application() -> None:
    """Aktualizacja z aplikacji (tryb cichy) kończy się ponownym uruchomieniem,
    a instalacja interaktywna nadal pyta o to w ostatnim kroku kreatora."""
    from transkryptor.packaging.bundle import BUNDLE_NAME
    from transkryptor.update.install import SILENT_INSTALL_ARGS

    script = render()
    run_section = script.split("[Run]", 1)[1]
    assert "Flags: nowait postinstall skipifsilent" in run_section
    assert (
        f'Filename: "{{app}}\\{BUNDLE_NAME}.exe"; Flags: nowait; Check: WizardSilent'
        in run_section
    )
    assert "/SILENT" in SILENT_INSTALL_ARGS
