"""Artefakt Windows: skrypt Inno Setup i wywołanie kompilatora ISCC.

Instalator pakuje katalog wytworzony przez PyInstallera w trybie onedir,
więc program działa bez globalnego Pythona, a biblioteki Qt pozostają
osobnymi plikami DLL, które użytkownik może podmienić (LGPL-3.0).

Skrypt ``.iss`` jest generowany, a nie trzymany jako plik w repozytorium:
wersja, nazwa artefaktu i identyfikator instalacji mają jedno źródło prawdy
w ``packaging.metadata``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from transkryptor.packaging.bundle import BUNDLE_NAME
from transkryptor.packaging.metadata import (
    APP_NAME,
    APP_SLUG,
    ICON_ICO,
    PUBLISHER,
    SUMMARY,
    VERSION,
    WINDOWS_APP_GUID,
)

ISCC = "ISCC.exe"
# Klucz ``QSettings("transkryptor", "transkryptor")`` z ui/settings_store.py
# (bez importu UI: pakietowanie nie zależy od Qt).
SETTINGS_REGISTRY_KEY = "transkryptor"
SCRIPT_NAME = f"{APP_SLUG}.iss"

# Typowe miejsca instalacji Inno Setup 6 na runnerach CI i stacjach roboczych.
ISCC_FALLBACK_PATHS = (
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)


def render_iss(
    dist_dir: Path,
    output_dir: Path,
    *,
    artifact_name: str,
    license_file: Path,
    version: str = VERSION,
    icon: Path = ICON_ICO,
) -> str:
    """Treść skryptu Inno Setup dla podanego katalogu z programem.

    ``OutputBaseFilename`` jest podawany bez rozszerzenia — Inno Setup dokłada
    ``.exe`` samodzielnie.
    """
    base_name = artifact_name[:-4] if artifact_name.endswith(".exe") else artifact_name
    lines = [
        f"; Instalator {APP_NAME} {version} — plik generowany przez",
        "; transkryptor.packaging.windows. Nie edytuj ręcznie.",
        "",
        "[Setup]",
        # Podwójna klamra otwierająca to w składni Inno Setup znak „{”.
        f"AppId={{{{{WINDOWS_APP_GUID}}}",
        f"AppName={APP_NAME}",
        f"AppVersion={version}",
        f"AppVerName={APP_NAME} {version}",
        f"AppPublisher={PUBLISHER}",
        f"VersionInfoVersion={version}",
        f"VersionInfoDescription={SUMMARY}",
        f"DefaultDirName={{autopf}}\\{APP_NAME}",
        f"DefaultGroupName={APP_NAME}",
        f"UninstallDisplayIcon={{app}}\\{BUNDLE_NAME}.exe",
        f"OutputDir={output_dir}",
        f"OutputBaseFilename={base_name}",
        f"LicenseFile={license_file}",
        "Compression=lzma2/max",
        "SolidCompression=yes",
        "WizardStyle=modern",
        # Artefakt jest 64-bitowy; instalacja na x86 nie ma sensu.
        "ArchitecturesAllowed=x64compatible",
        "ArchitecturesInstallIn64BitMode=x64compatible",
        # Instalacja dla jednego użytkownika nie wymaga uprawnień administratora.
        "PrivilegesRequired=lowest",
        "PrivilegesRequiredOverridesAllowed=dialog",
        "",
        "[Languages]",
        'Name: "polski"; MessagesFile: "compiler:Languages\\Polish.isl"',
        "",
        "[Tasks]",
        'Name: "desktopicon"; Description: "Utwórz skrót na pulpicie"; '
        'GroupDescription: "Skróty:"; Flags: unchecked',
        "",
        "[Files]",
        f'Source: "{dist_dir}\\*"; DestDir: "{{app}}"; '
        "Flags: ignoreversion recursesubdirs createallsubdirs",
        "",
        "[Icons]",
        f'Name: "{{group}}\\{APP_NAME}"; Filename: "{{app}}\\{BUNDLE_NAME}.exe"',
        'Name: "{group}\\Licencje i noty"; '
        'Filename: "{app}\\licenses\\THIRD-PARTY-NOTICES.md"',
        f'Name: "{{autodesktop}}\\{APP_NAME}"; '
        f'Filename: "{{app}}\\{BUNDLE_NAME}.exe"; Tasks: desktopicon',
        "",
        # Ustawienia użytkownika (QSettings) znikają razem z aplikacją;
        # instalator ich nie tworzy, tylko sprząta przy deinstalacji.
        "[Registry]",
        f'Root: HKCU; Subkey: "Software\\{SETTINGS_REGISTRY_KEY}"; '
        "Flags: uninsdeletekey dontcreatekey",
        "",
        "[Run]",
        f'Filename: "{{app}}\\{BUNDLE_NAME}.exe"; '
        f'Description: "Uruchom {APP_NAME}"; '
        "Flags: nowait postinstall skipifsilent",
        # Aktualizacja z aplikacji przebiega w trybie cichym (update/install.py)
        # i ma zakończyć się ponownym uruchomieniem programu.
        f'Filename: "{{app}}\\{BUNDLE_NAME}.exe"; '
        "Flags: nowait; Check: WizardSilent",
        "",
    ]
    if icon.is_file():
        lines.insert(lines.index("Compression=lzma2/max"), f"SetupIconFile={icon}")
    return "\n".join(lines) + "\n"


def write_iss(
    dist_dir: Path,
    output_dir: Path,
    script_path: Path,
    *,
    artifact_name: str,
    license_file: Path,
    version: str = VERSION,
) -> Path:
    """Zapisuje wygenerowany skrypt instalatora i zwraca jego ścieżkę."""
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        render_iss(
            dist_dir,
            output_dir,
            artifact_name=artifact_name,
            license_file=license_file,
            version=version,
        ),
        encoding="utf-8",
    )
    return script_path


def find_iscc(explicit: str | Path | None = None) -> str | None:
    """Ścieżka do kompilatora Inno Setup albo ``None``, gdy go nie ma."""
    if explicit:
        return str(explicit)
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for candidate in ISCC_FALLBACK_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def build(
    dist_dir: Path,
    output_dir: Path,
    *,
    artifact_name: str,
    license_file: Path,
    work_dir: Path | None = None,
    version: str = VERSION,
    tool: str | Path | None = None,
    runner=subprocess.run,
) -> Path:
    """Buduje instalator ``.exe`` i zwraca ścieżkę gotowego pliku."""
    compiler = find_iscc(tool)
    if compiler is None:
        raise FileNotFoundError(
            "Nie znaleziono kompilatora Inno Setup (ISCC.exe). Zainstaluj "
            "Inno Setup 6 albo wskaż go opcją --iscc; instrukcja: "
            "docs/release-process.md."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    script = write_iss(
        dist_dir,
        output_dir,
        (work_dir or output_dir) / SCRIPT_NAME,
        artifact_name=artifact_name,
        license_file=license_file,
        version=version,
    )
    result = runner([compiler, str(script)], check=False)
    if getattr(result, "returncode", 0) != 0:
        raise RuntimeError(f"ISCC zakończył się kodem {result.returncode}.")
    return output_dir / artifact_name


def required_tools() -> Sequence[str]:
    """Narzędzia zewnętrzne potrzebne do zbudowania artefaktu Windows."""
    return (ISCC,)


__all__ = [
    "SCRIPT_NAME",
    "build",
    "find_iscc",
    "render_iss",
    "required_tools",
    "write_iss",
]
