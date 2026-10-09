"""Testy narzędzia wydania spinającego wszystkie kroki budowania."""

from pathlib import Path

import pytest

from transkryptor.packaging import build as build_module
from transkryptor.packaging.bundle import BUNDLE_NAME
from transkryptor.packaging.metadata import targets


def test_target_is_detected_from_the_build_machine() -> None:
    assert build_module.detect_target("linux") == "linux"
    assert build_module.detect_target("win32") == "windows"


def test_unsupported_build_machine_is_reported() -> None:
    with pytest.raises(RuntimeError) as error:
        build_module.detect_target("darwin")
    assert "docs/release-process.md" in str(error.value)


@pytest.fixture
def prepared_dist(tmp_path):
    """Gotowy katalog aplikacji, jakby PyInstaller już się wykonał."""
    dist = tmp_path / "build" / "pyinstaller-dist" / BUNDLE_NAME
    dist.mkdir(parents=True)
    (dist / BUNDLE_NAME).write_bytes(b"ELF")
    return dist


def test_release_produces_artifact_checksums_and_notes(
    prepared_dist, tmp_path, monkeypatch
) -> None:
    artifact_name = targets()["linux"].artifact_name

    def fake_linux_build(dist_dir, output_dir, *, artifact_name, **_kwargs):
        assert (dist_dir / "licenses" / "LICENSE").is_file()
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / artifact_name
        artifact.write_bytes(b"AppImage")
        return artifact

    monkeypatch.setattr(build_module.linux, "build", fake_linux_build)

    result = build_module.build(
        target_key="linux",
        build_dir=tmp_path / "build",
        output_dir=tmp_path / "dist",
        skip_pyinstaller=True,
    )
    assert result.artifact.name == artifact_name
    assert result.checksums.name == "SHA256SUMS.txt"
    assert artifact_name in result.checksums.read_text(encoding="utf-8")
    assert result.release_notes.name == "RELEASE-NOTES.md"
    assert "## Prywatność" in result.release_notes.read_text(encoding="utf-8")


def test_licenses_are_placed_inside_the_application_directory(
    prepared_dist, tmp_path, monkeypatch
) -> None:
    """Wymaganie wydania mówi o artefakcie, nie o stronie pobierania."""

    def fake_linux_build(dist_dir, output_dir, *, artifact_name, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / artifact_name
        artifact.write_bytes(b"AppImage")
        return artifact

    monkeypatch.setattr(build_module.linux, "build", fake_linux_build)
    result = build_module.build(
        target_key="linux",
        build_dir=tmp_path / "build",
        output_dir=tmp_path / "dist",
        skip_pyinstaller=True,
    )
    assert result.licenses.root == prepared_dist / "licenses"
    assert (result.licenses.root / "THIRD-PARTY-NOTICES.md").is_file()
    assert (result.licenses.root / "MODEL-LICENSE.md").is_file()
    assert result.licenses.without_text() == ()


def test_skipping_pyinstaller_without_a_previous_build_is_reported(
    tmp_path,
) -> None:
    with pytest.raises(FileNotFoundError) as error:
        build_module.build(
            target_key="linux",
            build_dir=tmp_path / "build",
            output_dir=tmp_path / "dist",
            skip_pyinstaller=True,
        )
    assert "--skip-pyinstaller" in str(error.value)


def test_pyinstaller_failure_stops_the_release(tmp_path) -> None:
    class Result:
        returncode = 1

    with pytest.raises(RuntimeError) as error:
        build_module.run_pyinstaller(
            tmp_path, runner=lambda *_args, **_kwargs: Result()
        )
    assert "PyInstaller" in str(error.value)


def test_pyinstaller_is_called_with_isolated_work_directories(tmp_path) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def runner(command, **_kwargs):
        calls.append(command)
        bundled = tmp_path / "pyinstaller-dist" / BUNDLE_NAME
        bundled.mkdir(parents=True)
        return Result()

    bundled = build_module.run_pyinstaller(tmp_path, runner=runner)
    assert bundled.is_dir()
    command = calls[0]
    assert "--noconfirm" in command
    assert str(tmp_path / "pyinstaller-dist") in command
    assert str(tmp_path / "pyinstaller-work") in command


def test_missing_spec_file_is_reported(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        build_module.run_pyinstaller(tmp_path, spec=Path("/nie/ma/spec.spec"))


def test_second_platform_build_extends_the_same_release(
    prepared_dist, tmp_path, monkeypatch
) -> None:
    """Linux i Windows budowane do jednego dist/ dają wspólne sumy i noty."""
    output = tmp_path / "dist"
    names = {key: target.artifact_name for key, target in targets().items()}

    def fake_build(dist_dir, output_dir, *, artifact_name, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / artifact_name
        artifact.write_bytes(artifact_name.encode())
        return artifact

    monkeypatch.setattr(build_module.linux, "build", fake_build)
    monkeypatch.setattr(build_module.windows, "build", fake_build)
    # Artefakt innej wersji nie należy do tego wydania.
    output.mkdir()
    (output / "Transkryptor-0.0.1-x86_64.AppImage").write_bytes(b"stary")

    for key in ("linux", "windows"):
        result = build_module.build(
            target_key=key,
            build_dir=tmp_path / "build",
            output_dir=output,
            skip_pyinstaller=True,
        )

    sums = result.checksums.read_text(encoding="utf-8")
    notes = result.release_notes.read_text(encoding="utf-8")
    for name in names.values():
        assert name in sums
        assert name in notes
    assert "0.0.1" not in sums


def test_relative_directories_reach_the_installer_as_absolute_paths(
    tmp_path, monkeypatch
) -> None:
    """ISCC czyta ścieżki względne od katalogu .iss — muszą być bezwzględne."""
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "build" / "windows" / "pyinstaller-dist" / BUNDLE_NAME
    dist.mkdir(parents=True)
    seen: dict[str, Path] = {}

    def fake_windows_build(dist_dir, output_dir, *, artifact_name, license_file, **_kw):
        seen.update(dist_dir=dist_dir, output_dir=output_dir, license_file=license_file)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / artifact_name
        artifact.write_bytes(b"exe")
        return artifact

    monkeypatch.setattr(build_module.windows, "build", fake_windows_build)
    build_module.build(
        target_key="windows",
        build_dir=Path("build/windows"),
        output_dir=Path("dist"),
        skip_pyinstaller=True,
    )
    assert all(path.is_absolute() for path in seen.values())
    assert seen["license_file"].is_file()


def test_finalize_covers_artifacts_collected_from_both_runners(tmp_path) -> None:
    """CI składa artefakty z dwóch runnerów i liczy dla nich wspólne sumy i noty."""
    output = tmp_path / "dist"
    output.mkdir()
    names = [target.artifact_name for target in targets().values()]
    for name in names:
        (output / name).write_bytes(name.encode())
    # Pliki pojedynczych runnerów są nadpisywane wspólną wersją.
    (output / "SHA256SUMS.txt").write_text("stare\n", encoding="utf-8")

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## Nieopublikowane\n\n- Nowość z historii.\n", encoding="utf-8"
    )

    code = build_module.main(
        [
            "--finalize",
            "--output-dir",
            str(output),
            "--source-url",
            "https://x/src",
            "--changelog",
            str(changelog),
        ]
    )

    assert code == 0
    sums = (output / "SHA256SUMS.txt").read_text(encoding="utf-8")
    notes = (output / "RELEASE-NOTES.md").read_text(encoding="utf-8")
    assert sorted(line.split()[1] for line in sums.splitlines()) == sorted(names)
    for name in names:
        assert name in notes
    assert "https://x/src" in notes
    assert "- Nowość z historii." in notes


def test_finalize_without_artifacts_fails(tmp_path, capsys) -> None:
    assert build_module.main(["--finalize", "--output-dir", str(tmp_path)]) == 1
    assert "Brak artefaktów" in capsys.readouterr().err


def test_finalize_without_changelog_entry_fails(tmp_path, capsys) -> None:
    """Noty bez nowości byłyby kopią poprzednich — wydanie się zatrzymuje."""
    output = tmp_path / "dist"
    output.mkdir()
    for target in targets().values():
        (output / target.artifact_name).write_bytes(b"x")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## Nieopublikowane\n", encoding="utf-8")

    code = build_module.main(
        ["--finalize", "--output-dir", str(output), "--changelog", str(changelog)]
    )

    assert code == 1
    assert "Nieopublikowane" in capsys.readouterr().err
    assert not (output / "RELEASE-NOTES.md").exists()
