"""Narzędzie wydania: od kodu źródłowego do podpisanego sumą artefaktu.

Jedno polecenie wykonuje kroki procesu wydania z ``specs/delivery.md``:
budowanie runtime PyInstallerem, dołożenie kompletu licencji, spakowanie
artefaktu dla bieżącej platformy, sumy kontrolne i noty wydania.

    uv run --group packaging python -m transkryptor.packaging

Narzędzie nie jest częścią procesu uruchomieniowego aplikacji.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from transkryptor.packaging import linux, windows
from transkryptor.packaging.bundle import BUNDLE_NAME
from transkryptor.packaging.changelog import CHANGELOG_FILE, ChangelogError, whats_new
from transkryptor.packaging.checksums import checksums_for, write_checksums
from transkryptor.packaging.licenses import LicenseBundle, write_license_bundle
from transkryptor.packaging.metadata import (
    PYINSTALLER_SPEC,
    REPO_ROOT,
    VERSION,
    Target,
    target_for,
    targets,
)
from transkryptor.packaging.release_notes import write_release_notes

DEFAULT_BUILD_DIR = REPO_ROOT / "build"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"


@dataclass(frozen=True)
class BuildResult:
    """Wynik budowania: artefakt i pliki, które mu towarzyszą."""

    target: Target
    artifact: Path
    checksums: Path
    release_notes: Path
    licenses: LicenseBundle


def detect_target(platform: str = sys.platform) -> str:
    """Platforma docelowa wyprowadzona z systemu, na którym trwa budowanie.

    Artefakty powstają natywnie: instalator Windows na Windows, AppImage na
    Linuxie. Budowanie na innym systemie dałoby plik, którego nie da się
    sprawdzić na miejscu, więc kończy się czytelnym błędem.
    """
    if platform.startswith("win"):
        return "windows"
    if platform.startswith("linux"):
        return "linux"
    raise RuntimeError(
        f"System „{platform}” nie jest platformą wydania. Zbuduj artefakt na "
        "Windows albo Linuxie (patrz docs/release-process.md)."
    )


def run_pyinstaller(
    build_dir: Path,
    *,
    spec: Path = PYINSTALLER_SPEC,
    runner=subprocess.run,
) -> Path:
    """Buduje katalog aplikacji (tryb onedir) i zwraca ścieżkę do niego."""
    if not spec.is_file():
        raise FileNotFoundError(f"Brak pliku specyfikacji PyInstallera: {spec}")
    dist_root = build_dir / "pyinstaller-dist"
    work_root = build_dir / "pyinstaller-work"
    for path in (dist_root, work_root):
        if path.exists():
            shutil.rmtree(path)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec),
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
    ]
    result = runner(command, check=False, cwd=str(REPO_ROOT))
    if getattr(result, "returncode", 0) != 0:
        raise RuntimeError(f"PyInstaller zakończył się kodem {result.returncode}.")
    bundled = dist_root / BUNDLE_NAME
    if not bundled.is_dir():
        raise RuntimeError(f"PyInstaller nie utworzył katalogu aplikacji: {bundled}")
    return bundled


def build(
    *,
    target_key: str | None = None,
    build_dir: Path = DEFAULT_BUILD_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    version: str = VERSION,
    skip_pyinstaller: bool = False,
    source_url: str | None = None,
    release_date: date_type | None = None,
    changelog: Path = CHANGELOG_FILE,
    tool: str | Path | None = None,
    runner=subprocess.run,
) -> BuildResult:
    """Wykonuje pełne budowanie artefaktu dla jednej platformy."""
    target = target_for(target_key or detect_target(), version)
    # Brak opisu zmian wychodzi przed kilkuminutowym budowaniem, nie po nim.
    whats_new(version, changelog)
    # Ścieżki bezwzględne: trafiają m.in. do skryptu Inno Setup, a ISCC
    # rozwiązuje ścieżki względne od katalogu skryptu, nie od bieżącego.
    build_dir = Path(build_dir).resolve()
    output_dir = Path(output_dir).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = build_dir / "pyinstaller-dist" / BUNDLE_NAME
    if skip_pyinstaller:
        if not dist_dir.is_dir():
            raise FileNotFoundError(
                f"Brak gotowego katalogu aplikacji: {dist_dir}. Uruchom "
                "budowanie bez --skip-pyinstaller."
            )
    else:
        dist_dir = run_pyinstaller(build_dir, runner=runner)

    # Licencje leżą w artefakcie obok programu: wymaganie wydania mówi
    # o artefakcie, a nie o stronie pobierania.
    licenses = write_license_bundle(dist_dir / "licenses")

    if target.key == "windows":
        artifact = windows.build(
            dist_dir,
            output_dir,
            artifact_name=target.artifact_name,
            license_file=licenses.root / "LICENSE",
            work_dir=build_dir,
            version=version,
            tool=tool,
            runner=runner,
        )
    else:
        artifact = linux.build(
            dist_dir,
            output_dir,
            artifact_name=target.artifact_name,
            work_dir=build_dir,
            version=version,
            tool=tool,
            runner=runner,
        )
    if not artifact.is_file():
        raise RuntimeError(f"Budowanie nie wytworzyło artefaktu: {artifact}")

    checksums, notes = finalize(
        output_dir,
        version=version,
        release_date=release_date,
        source_url=source_url,
        changelog=changelog,
    )
    return BuildResult(
        target=target,
        artifact=artifact,
        checksums=checksums,
        release_notes=notes,
        licenses=licenses,
    )


def finalize(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    version: str = VERSION,
    source_url: str | None = None,
    release_date: date_type | None = None,
    changelog: Path = CHANGELOG_FILE,
) -> tuple[Path, Path]:
    """Sumy kontrolne i noty dla wszystkich artefaktów wersji w katalogu.

    Sumy i noty obejmują wszystkie artefakty tej wersji leżące w katalogu
    wynikowym: kolejne budowania (Linux, potem Windows) dopisują się do
    wspólnego wydania zamiast nadpisywać poprzedni wpis. CI wywołuje to
    osobno (``--finalize``) po zebraniu artefaktów z obu runnerów.
    Nowości wersji pochodzą z ``changelog`` (``CHANGELOG.md``).
    """
    output_dir = Path(output_dir).resolve()
    released = release_artifacts(output_dir, version)
    if not released:
        raise FileNotFoundError(
            f"Brak artefaktów wersji {version} w katalogu {output_dir}."
        )
    news = whats_new(version, changelog)
    checksums = write_checksums(released, output_dir)
    notes = write_release_notes(
        checksums_for(released),
        output_dir,
        version=version,
        release_date=release_date,
        source_url=source_url,
        whats_new=news,
    )
    return checksums, notes


def release_artifacts(output_dir: Path, version: str = VERSION) -> list[Path]:
    """Artefakty podanej wersji obecne w katalogu wynikowym (Linux, Windows)."""
    candidates = (
        output_dir / target.artifact_name for target in targets(version).values()
    )
    return sorted(path for path in candidates if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.packaging", description=__doc__
    )
    parser.add_argument(
        "--target",
        choices=("auto", "windows", "linux"),
        default="auto",
        help="platforma docelowa (domyślnie: wykryta z systemu budowania)",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=DEFAULT_BUILD_DIR,
        help="katalog roboczy budowania",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="katalog na gotowe artefakty wydania",
    )
    parser.add_argument(
        "--skip-pyinstaller",
        action="store_true",
        help="użyj gotowego katalogu aplikacji z poprzedniego przebiegu",
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="adres kodu źródłowego wydania wpisywany do not wydania",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=CHANGELOG_FILE,
        help="historia zmian, z której pochodzą nowości w notach wydania",
    )
    parser.add_argument(
        "--tool",
        default=None,
        help="ścieżka do appimagetool lub ISCC.exe, gdy nie ma ich w PATH",
    )
    parser.add_argument(
        "--finalize",
        action="store_true",
        help=(
            "bez budowania: wspólne sumy kontrolne i noty wydania dla "
            "artefaktów obu platform obecnych w katalogu wynikowym"
        ),
    )
    args = parser.parse_args(argv)

    if args.finalize:
        try:
            checksums, notes = finalize(
                args.output_dir,
                source_url=args.source_url,
                changelog=args.changelog,
            )
        except (FileNotFoundError, ChangelogError) as error:
            print(f"Przerwane: {error}", file=sys.stderr)
            return 1
        print(f"Sumy kontrolne:{checksums}")
        print(f"Noty wydania:  {notes}")
        return 0

    try:
        result = build(
            target_key=None if args.target == "auto" else args.target,
            build_dir=args.build_dir,
            output_dir=args.output_dir,
            skip_pyinstaller=args.skip_pyinstaller,
            source_url=args.source_url,
            changelog=args.changelog,
            tool=args.tool,
        )
    except (FileNotFoundError, RuntimeError, ChangelogError) as error:
        print(f"Budowanie przerwane: {error}", file=sys.stderr)
        return 1

    missing = result.licenses.without_text()
    if missing:
        names = ", ".join(dist.name for dist in missing)
        print(
            f"Uwaga: brak tekstu licencji dla zależności: {names}. "
            "Uzupełnij assets/licenses przed publikacją.",
            file=sys.stderr,
        )
    print(f"Artefakt:      {result.artifact}")
    print(f"Sumy kontrolne:{result.checksums}")
    print(f"Noty wydania:  {result.release_notes}")
    return 0


__all__ = [
    "BuildResult",
    "build",
    "detect_target",
    "finalize",
    "main",
    "release_artifacts",
    "run_pyinstaller",
]
