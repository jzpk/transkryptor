"""Dane wejściowe PyInstallera: skrypt startowy, ukryte importy i zasoby.

Plik specyfikacji ``packaging/transkryptor.spec`` jest celowo cienki — cała
wiedza o tym, co musi trafić do artefaktu, jest tutaj, żeby dała się
przetestować bez uruchamiania budowania.

Tryb pakowania to **onedir**: biblioteki Qt leżą w artefakcie jako osobne
pliki dynamiczne i użytkownik może je podmienić. To warunek zgodności
z LGPL-3.0 dla Qt (patrz ``licenses.NATIVE_LIBRARY_NOTES``), dlatego nie
wolno zamienić go na onefile.
"""

from __future__ import annotations

from importlib import util as importlib_util
from pathlib import Path

from transkryptor.packaging.metadata import (
    APP_SLUG,
    ICON_ICO,
    ICON_PNG,
    REPO_ROOT,
)

#: Skrypt uruchamiany przez artefakt — ten sam punkt wejścia co ``uv run``.
ENTRY_SCRIPT = REPO_ROOT / "src" / "transkryptor" / "__main__.py"

#: Katalog z kodem aplikacji dodawany do ścieżki analizy PyInstallera.
SOURCE_ROOT = REPO_ROOT / "src"

#: Nazwa katalogu i pliku wykonywalnego wewnątrz artefaktu.
BUNDLE_NAME = APP_SLUG

# Moduły wczytywane leniwie (import wewnątrz funkcji) albo wybierane w czasie
# działania. Analiza statyczna zwykle je znajduje, ale ukryty import jest
# tańszy niż wydanie, w którym brakuje silnika ASR.
HIDDEN_IMPORTS = (
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "tokenizers",
    "av",
    "httpx",
    "huggingface_hub",
    "docx",
    "PySide6.QtMultimedia",
    "PySide6.QtSvg",  # ikony interfejsu (ui/icons.py)
)

# Pakiety, które nie mają prawa trafić do artefaktu: narzędzia deweloperskie
# oraz moduły Qt, których aplikacja nie używa (oszczędność ok. 400 MB).
EXCLUDED_MODULES = (
    "tkinter",
    "pytest",
    "pytestqt",
    "PyInstaller",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtDesigner",
    "PySide6.QtWebSockets",
)

# Zasoby pakietów, których PyInstaller nie znajdzie sam, bo są czytane
# ze ścieżki względnej w czasie działania.
#
# ``faster_whisper/assets`` zawiera model wykrywania mowy (Silero VAD),
# wywoływany przez ``vad_filter=True`` w ``asr.engine.transcribe``. Bez tego
# pliku transkrypcja w artefakcie kończy się błędem otwarcia pliku.
PACKAGE_DATA = (("faster_whisper", "assets"),)


def package_directory(package: str) -> Path:
    """Katalog zainstalowanego pakietu albo ``FileNotFoundError``."""
    spec = importlib_util.find_spec(package)
    locations = list(spec.submodule_search_locations or ()) if spec else []
    if not locations:
        raise FileNotFoundError(
            f"Pakiet „{package}” nie jest zainstalowany w tym środowisku — "
            "uruchom budowanie przez „uv run --group packaging”."
        )
    return Path(locations[0])


def collect_datas() -> list[tuple[str, str]]:
    """Pary ``(ścieżka_źródłowa, katalog_w_artefakcie)`` dla PyInstallera."""
    datas: list[tuple[str, str]] = []
    for package, subdir in PACKAGE_DATA:
        source = package_directory(package) / subdir
        if not source.is_dir():
            raise FileNotFoundError(
                f"Brak zasobu „{package}/{subdir}” w zainstalowanym pakiecie."
            )
        for entry in sorted(source.iterdir()):
            if entry.is_file() and entry.suffix not in {".pyc"}:
                datas.append((str(entry), f"{package}/{subdir}"))
    return datas


def icon_for(platform: str) -> str | None:
    """Ikona dla pliku wykonywalnego: ICO na Windows, PNG w pozostałych."""
    icon = ICON_ICO if platform.startswith("win") else ICON_PNG
    return str(icon) if icon.is_file() else None


def analysis_options(platform: str) -> dict[str, object]:
    """Komplet argumentów dla ``Analysis`` i ``EXE`` w pliku specyfikacji."""
    return {
        "scripts": [str(ENTRY_SCRIPT)],
        "pathex": [str(SOURCE_ROOT)],
        "datas": collect_datas(),
        "hiddenimports": list(HIDDEN_IMPORTS),
        "excludes": list(EXCLUDED_MODULES),
        "name": BUNDLE_NAME,
        "console": False,
        "icon": icon_for(platform),
        # UPX psuje podpisane biblioteki Qt i bywa wykrywany jako zagrożenie;
        # artefakt wydania musi dać się uruchomić bez wyjątków w antywirusie.
        "upx": False,
        # Bez strip: binutils z Ubuntu 22.04 (bazowy system AppImage) psuje
        # biblioteki przepakowane patchelf-em, np. OpenBLAS z kół numpy
        # („ELF load command address/offset not page-aligned”) — a bez numpy
        # nie działa ASR. Zysk z obcięcia symboli to kilka MB.
        "strip": False,
    }


__all__ = [
    "BUNDLE_NAME",
    "ENTRY_SCRIPT",
    "EXCLUDED_MODULES",
    "HIDDEN_IMPORTS",
    "PACKAGE_DATA",
    "SOURCE_ROOT",
    "analysis_options",
    "collect_datas",
    "icon_for",
    "package_directory",
]
