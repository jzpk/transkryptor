"""Artefakt Linuxa: AppDir z katalogu PyInstallera i obraz AppImage.

AppImage uruchamia się na współczesnych dystrybucjach bez instalacji
i bez globalnego Pythona — dokładnie tego wymaga bramka fazy 05.

Budowa przebiega w dwóch krokach, żeby dała się sprawdzić bez narzędzi
zewnętrznych: najpierw powstaje katalog ``AppDir`` (czysta praca na plikach,
objęta testami), a dopiero potem ``appimagetool`` zamienia go w jeden plik.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from transkryptor.packaging.bundle import BUNDLE_NAME
from transkryptor.packaging.metadata import (
    APP_NAME,
    APP_SLUG,
    ICON_PNG,
    SUMMARY,
    VERSION,
)

APPIMAGE_TOOL = "appimagetool"

# AppRun ustala katalog obrazu i uruchamia program z katalogu onedir.
# ``readlink -f`` jest potrzebne, bo AppImage montuje się pod zmienną ścieżką.
APPRUN_SCRIPT = f"""#!/bin/sh
# Punkt wejścia AppImage dla {APP_NAME}.
set -eu
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/{BUNDLE_NAME}/{BUNDLE_NAME}" "$@"
"""


def desktop_entry(version: str = VERSION) -> str:
    """Treść pliku ``.desktop`` wymaganego przez AppImage i menu systemowe."""
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={APP_NAME}",
            f"Comment={SUMMARY}",
            f"Exec={APP_SLUG}",
            f"Icon={APP_SLUG}",
            "Terminal=false",
            "Categories=AudioVideo;Audio;Utility;",
            "Keywords=transkrypcja;fonetyka;ASR;audio;",
            f"X-AppImage-Version={version}",
            "",
        ]
    )


def build_appdir(
    dist_dir: Path,
    appdir: Path,
    *,
    version: str = VERSION,
    icon: Path = ICON_PNG,
) -> Path:
    """Układa AppDir z katalogu onedir wytworzonego przez PyInstallera.

    Struktura jest zgodna z oczekiwaniami ``appimagetool``: ``AppRun``, plik
    ``.desktop`` i ikona w korzeniu, a program i jego biblioteki w
    ``usr/lib``.
    """
    if not dist_dir.is_dir():
        raise FileNotFoundError(f"Brak katalogu z wynikiem PyInstallera: {dist_dir}")
    if appdir.exists():
        shutil.rmtree(appdir)
    target = appdir / "usr" / "lib" / BUNDLE_NAME
    target.parent.mkdir(parents=True)
    shutil.copytree(dist_dir, target, symlinks=True)

    apprun = appdir / "AppRun"
    apprun.write_text(APPRUN_SCRIPT, encoding="utf-8")
    apprun.chmod(0o755)

    desktop_name = f"{APP_SLUG}.desktop"
    (appdir / desktop_name).write_text(desktop_entry(version), encoding="utf-8")
    applications = appdir / "usr" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(appdir / desktop_name, applications / desktop_name)

    if icon.is_file():
        shutil.copyfile(icon, appdir / f"{APP_SLUG}.png")
        icons = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icons.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icon, icons / f"{APP_SLUG}.png")
    return appdir


def find_appimagetool(explicit: str | Path | None = None) -> str | None:
    """Ścieżka do ``appimagetool`` albo ``None``, gdy narzędzia nie ma."""
    if explicit:
        return str(explicit)
    return shutil.which(APPIMAGE_TOOL)


def build_appimage(
    appdir: Path,
    output: Path,
    *,
    tool: str | Path | None = None,
    runner=subprocess.run,
) -> Path:
    """Zamienia AppDir w plik AppImage.

    Zgłasza ``FileNotFoundError``, gdy ``appimagetool`` nie jest dostępny —
    budowanie artefaktu nie może po cichu wyprodukować niepełnego wydania.
    """
    executable = find_appimagetool(tool)
    if executable is None:
        raise FileNotFoundError(
            "Nie znaleziono „appimagetool”. Zainstaluj narzędzie albo wskaż je "
            "opcją --appimagetool; instrukcja: docs/release-process.md."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    # Powtarzalny obraz: bez automatycznego podpisu i bez aktualizacji delta.
    environment.setdefault("ARCH", "x86_64")
    result = runner(
        [executable, "--no-appstream", str(appdir), str(output)],
        check=False,
        env=environment,
    )
    if getattr(result, "returncode", 0) != 0:
        raise RuntimeError(f"appimagetool zakończył się kodem {result.returncode}.")
    if output.is_file():
        output.chmod(0o755)
    return output


def build(
    dist_dir: Path,
    output_dir: Path,
    *,
    artifact_name: str,
    work_dir: Path | None = None,
    version: str = VERSION,
    tool: str | Path | None = None,
    runner=subprocess.run,
) -> Path:
    """Pełny artefakt Linuxa: AppDir, a następnie plik AppImage."""
    appdir = (work_dir or output_dir.parent) / f"{APP_NAME}.AppDir"
    build_appdir(dist_dir, appdir, version=version)
    return build_appimage(appdir, output_dir / artifact_name, tool=tool, runner=runner)


def required_tools() -> Sequence[str]:
    """Narzędzia zewnętrzne potrzebne do zbudowania artefaktu Linuxa."""
    return (APPIMAGE_TOOL,)


__all__ = [
    "APPRUN_SCRIPT",
    "build",
    "build_appdir",
    "build_appimage",
    "desktop_entry",
    "find_appimagetool",
    "required_tools",
]
