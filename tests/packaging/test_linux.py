"""Testy artefaktu Linuxa: struktura AppDir i wywołanie appimagetool."""

import pytest

from transkryptor.packaging import linux
from transkryptor.packaging.bundle import BUNDLE_NAME


@pytest.fixture
def dist_dir(tmp_path):
    """Imitacja katalogu wytworzonego przez PyInstallera w trybie onedir."""
    source = tmp_path / "pyinstaller-dist" / BUNDLE_NAME
    (source / "_internal").mkdir(parents=True)
    executable = source / BUNDLE_NAME
    executable.write_bytes(b"ELF")
    executable.chmod(0o755)
    (source / "_internal" / "qt.so").write_bytes(b"lib")
    (source / "licenses").mkdir()
    (source / "licenses" / "LICENSE").write_text("GPL", encoding="utf-8")
    return source


def test_appdir_has_the_layout_appimagetool_expects(dist_dir, tmp_path) -> None:
    appdir = linux.build_appdir(dist_dir, tmp_path / "Transkryptor.AppDir")
    assert (appdir / "AppRun").is_file()
    assert (appdir / "transkryptor.desktop").is_file()
    assert (appdir / "transkryptor.png").is_file()
    assert (appdir / "usr" / "lib" / BUNDLE_NAME / BUNDLE_NAME).is_file()


def test_apprun_is_executable_and_starts_the_bundled_program(
    dist_dir, tmp_path
) -> None:
    appdir = linux.build_appdir(dist_dir, tmp_path / "Transkryptor.AppDir")
    apprun = appdir / "AppRun"
    assert apprun.stat().st_mode & 0o111
    script = apprun.read_text(encoding="utf-8")
    assert f"usr/lib/{BUNDLE_NAME}/{BUNDLE_NAME}" in script
    # AppImage montuje się pod zmienną ścieżką — bez readlink skrypt zgubi katalog.
    assert "readlink -f" in script


def test_licenses_travel_with_the_program(dist_dir, tmp_path) -> None:
    appdir = linux.build_appdir(dist_dir, tmp_path / "Transkryptor.AppDir")
    assert (appdir / "usr" / "lib" / BUNDLE_NAME / "licenses" / "LICENSE").is_file()


def test_desktop_entry_is_valid_for_menus(tmp_path) -> None:
    entry = linux.desktop_entry("1.2.3")
    assert entry.startswith("[Desktop Entry]")
    assert "Type=Application" in entry
    assert "Name=Transkryptor" in entry
    assert "Icon=transkryptor" in entry
    assert "X-AppImage-Version=1.2.3" in entry


def test_desktop_entry_is_also_installed_in_usr_share(dist_dir, tmp_path) -> None:
    appdir = linux.build_appdir(dist_dir, tmp_path / "Transkryptor.AppDir")
    installed = appdir / "usr" / "share" / "applications" / "transkryptor.desktop"
    assert installed.read_text(encoding="utf-8") == (
        appdir / "transkryptor.desktop"
    ).read_text(encoding="utf-8")


def test_rebuilding_replaces_a_stale_appdir(dist_dir, tmp_path) -> None:
    appdir = tmp_path / "Transkryptor.AppDir"
    linux.build_appdir(dist_dir, appdir)
    stale = appdir / "usr" / "lib" / BUNDLE_NAME / "stary-plik"
    stale.write_text("poprzednie wydanie", encoding="utf-8")
    linux.build_appdir(dist_dir, appdir)
    assert not stale.exists()


def test_missing_dist_directory_is_reported(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        linux.build_appdir(tmp_path / "nie-ma", tmp_path / "AppDir")


def test_build_without_appimagetool_explains_what_to_install(
    dist_dir, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(linux.shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError) as error:
        linux.build(
            dist_dir,
            tmp_path / "out",
            artifact_name="Transkryptor.AppImage",
            work_dir=tmp_path,
        )
    assert "appimagetool" in str(error.value)


def test_build_invokes_appimagetool_with_the_appdir(dist_dir, tmp_path) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["ARCH"] == "x86_64"
        target = tmp_path / "out" / "Transkryptor.AppImage"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"AppImage")
        return Result()

    artifact = linux.build(
        dist_dir,
        tmp_path / "out",
        artifact_name="Transkryptor.AppImage",
        work_dir=tmp_path,
        tool="/usr/local/bin/appimagetool",
        runner=runner,
    )
    assert artifact.is_file()
    assert artifact.stat().st_mode & 0o111
    assert calls[0][0] == "/usr/local/bin/appimagetool"
    assert str(tmp_path / "Transkryptor.AppDir") in calls[0]


def test_failed_appimagetool_run_is_reported(dist_dir, tmp_path) -> None:
    class Result:
        returncode = 2

    with pytest.raises(RuntimeError) as error:
        linux.build(
            dist_dir,
            tmp_path / "out",
            artifact_name="Transkryptor.AppImage",
            work_dir=tmp_path,
            tool="appimagetool",
            runner=lambda *_args, **_kwargs: Result(),
        )
    assert "kodem 2" in str(error.value)
