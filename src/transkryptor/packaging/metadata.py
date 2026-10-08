"""Tożsamość wydania: nazwy artefaktów, dane instalatora i wymagania sprzętowe.

Jedno źródło prawdy dla wszystkich materiałów fazy 05: skryptu PyInstaller,
instalatora Inno Setup, AppImage, not wydania i dokumentacji użytkownika.
Dzięki temu wersja, nazwa pliku i wymagania nie rozjeżdżają się między
artefaktem a tekstem, który go opisuje.

Granica modułu: kod budowania nie jest częścią procesu uruchomieniowego
aplikacji — importuje go wyłącznie narzędzie wydania.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transkryptor import __version__

APP_NAME = "Transkryptor"
APP_SLUG = "transkryptor"
VERSION = __version__

# Krótki opis używany w instalatorze, pliku .desktop i notach wydania.
SUMMARY = "Lokalna aplikacja do ręcznej transkrypcji fonetycznej języka polskiego"
PUBLISHER = "Projekt Transkryptor"
LICENSE_ID = "GPL-3.0-or-later"

# Stały identyfikator instalacji dla Inno Setup (sam GUID, bez klamer —
# składnię ``AppId={{GUID}`` tworzy szablon instalatora). Nie wolno go zmieniać
# między wydaniami: po zmianie Windows potraktuje aktualizację jako drugi
# program i pozostawi dwie instalacje obok siebie.
WINDOWS_APP_GUID = "7F3B5A12-9C4D-4E8A-B6F1-2D0E5C7A9B34"

# Katalog źródeł budowania (repozytorium) i plik specyfikacji PyInstaller.
REPO_ROOT = Path(__file__).resolve().parents[3]
PYINSTALLER_SPEC = REPO_ROOT / "packaging" / "transkryptor.spec"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PNG = ASSETS_DIR / "icon.png"
ICON_ICO = ASSETS_DIR / "icon.ico"

# Minimalna wersja glibc artefaktu Linuxa wynika z systemu, na którym powstaje
# AppImage (runner CI: Ubuntu 22.04). Zapisana tutaj, bo trafia do not wydania.
LINUX_GLIBC_BASELINE = "2.35"
LINUX_BUILD_BASELINE = "Ubuntu 22.04 (x86_64)"
WINDOWS_BASELINE = "Windows 10 lub 11 (x64)"


@dataclass(frozen=True)
class Requirement:
    """Jedno wymaganie sprzętowe z minimum, zaleceniem i podstawą liczby."""

    resource: str
    minimum: str
    recommended: str
    basis: str


# Liczby pochodzą z pomiarów fazy 04 (docs/benchmarks-asr.md). Wiersz CPU jest
# rekomendacją, a nie pomiarem na maszynie czterordzeniowej — tak jest
# opisany również w dokumentacji i notach wydania.
HARDWARE_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        resource="RAM",
        minimum="4 GB",
        recommended="8 GB",
        basis="zmierzony szczyt 2.08 GB plus zapas na system i interfejs",
    ),
    Requirement(
        resource="Dysk",
        minimum="3 GB wolnego miejsca",
        recommended="—",
        basis="model 1.53 GB, aplikacja ok. 0.5 GB oraz pliki tymczasowe",
    ),
    Requirement(
        resource="CPU",
        minimum="4 rdzenie z obsługą kwantyzacji int8",
        recommended="8 rdzeni lub więcej",
        basis="rekomendacja, nie pomiar: silnik wykorzystał średnio 4 rdzenie",
    ),
    Requirement(
        resource="Sieć",
        minimum="jednorazowe pobranie modelu (1.53 GB)",
        recommended="—",
        basis="po pobraniu praca bez dostępu do Internetu",
    ),
)

# Zmierzony stosunek czasu transkrypcji do długości nagrania oraz opis
# maszyny, na której powstał pomiar (faza 04, docs/benchmarks-asr.md).
REALTIME_FACTOR = "0.54×"
BENCHMARK_MACHINE = "16 wątków logicznych, CPU, kwantyzacja int8"


@dataclass(frozen=True)
class Target:
    """Platforma docelowa wraz z nazwą artefaktu wydania."""

    key: str
    display_name: str
    artifact_name: str
    baseline: str


def targets(version: str = VERSION) -> dict[str, Target]:
    """Opis obu platform docelowych dla podanej wersji."""
    return {
        "windows": Target(
            key="windows",
            display_name="Windows 10/11 (x64)",
            artifact_name=f"{APP_NAME}-{version}-windows-x64-setup.exe",
            baseline=WINDOWS_BASELINE,
        ),
        "linux": Target(
            key="linux",
            display_name="Linux (x86_64, AppImage)",
            artifact_name=f"{APP_NAME}-{version}-x86_64.AppImage",
            baseline=(
                f"{LINUX_BUILD_BASELINE}, glibc {LINUX_GLIBC_BASELINE} lub nowsza"
            ),
        ),
    }


def target_for(key: str, version: str = VERSION) -> Target:
    """Zwraca opis platformy albo zgłasza ``KeyError`` z czytelną listą."""
    available = targets(version)
    if key not in available:
        raise KeyError(
            f"Nieznana platforma „{key}”. Dostępne: {', '.join(sorted(available))}."
        )
    return available[key]


__all__ = [
    "APP_NAME",
    "APP_SLUG",
    "HARDWARE_REQUIREMENTS",
    "ICON_ICO",
    "ICON_PNG",
    "LICENSE_ID",
    "PUBLISHER",
    "PYINSTALLER_SPEC",
    "REPO_ROOT",
    "SUMMARY",
    "Requirement",
    "Target",
    "VERSION",
    "WINDOWS_APP_GUID",
    "target_for",
    "targets",
]
