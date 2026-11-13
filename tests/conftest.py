"""Wspólna konfiguracja testów.

Testy end-to-end (``tests/e2e``) są zbierane tylko z opcją ``--e2e`` - zwykły
przebieg ``pytest`` (CI dla PR i main) uruchamia same testy jednostkowe
i integracyjne, a testy e2e biegną w workflow wydania.

Cały przebieg jest odcięty od konfiguracji i danych dewelopera: katalogi
użytkownika (XDG, ``APPDATA``) i domyślne położenie ``QSettings`` wskazują
katalog tymczasowy, zanim test utworzy jakikolwiek magazyn ustawień. To
zabezpieczenie globalne - działa także wtedy, gdy test cofnie poprawki
fixture'ów (np. ``monkeypatch.undo()``) albo zapomni o izolacji.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from transkryptor import i18n

E2E_DIR = Path(__file__).parent / "e2e"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("transkryptor")
    group.addoption(
        "--e2e",
        action="store_true",
        help="uruchom testy end-to-end z tests/e2e (domyślnie pomijane)",
    )
    group.addoption(
        "--update-golden",
        action="store_true",
        help="zapisz bieżące wyniki testów e2e jako pliki wzorcowe",
    )


# Katalogi użytkownika podmieniane na czas testów (Linux i Windows).
USER_DIR_VARIABLES = (
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "APPDATA",
    "LOCALAPPDATA",
)
_sandbox: Path | None = None
# Katalog modeli ASR dewelopera sprzed izolacji - tylko do odczytu w testach
# na prawdziwym modelu (``asr_model``); nic w nim nie jest zapisywane.
REAL_MODELS_ROOT: Path | None = None


def _isolate_user_dirs() -> Path:
    """Katalogi użytkownika i ``QSettings`` w katalogu tymczasowym."""
    from PySide6.QtCore import QSettings

    root = Path(tempfile.mkdtemp(prefix="transkryptor-tests-"))
    for name in USER_DIR_VARIABLES:
        directory = root / name.lower()
        directory.mkdir()
        os.environ[name] = str(directory)
    config = str(root / "xdg_config_home")
    for settings_format in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(settings_format, QSettings.Scope.UserScope, config)
        QSettings.setPath(settings_format, QSettings.Scope.SystemScope, config)
    return root


def pytest_configure(config: pytest.Config) -> None:
    global _sandbox, REAL_MODELS_ROOT
    from transkryptor.asr.models import default_models_root

    REAL_MODELS_ROOT = default_models_root()
    _sandbox = _isolate_user_dirs()
    if config.getoption("--e2e"):
        return
    for arg in config.args:
        path = Path(config.invocation_params.dir, arg.split("::", 1)[0]).resolve()
        if path == E2E_DIR or E2E_DIR in path.parents:
            raise pytest.UsageError("testy e2e uruchamia: pytest --e2e tests/e2e")


@pytest.fixture(scope="session")
def real_models_root() -> Path:
    """Katalog pobranych modeli ASR dewelopera (tylko do odczytu)."""
    assert REAL_MODELS_ROOT is not None
    return REAL_MODELS_ROOT


def pytest_unconfigure(config: pytest.Config) -> None:
    if _sandbox is not None:
        shutil.rmtree(_sandbox, ignore_errors=True)


@pytest.fixture(autouse=True)
def settings_stay_in_sandbox():
    """Po teście domyślny magazyn ustawień nadal leży w katalogu testów."""
    yield
    from PySide6.QtCore import QSettings

    from transkryptor.ui.settings_store import (
        SETTINGS_APPLICATION,
        SETTINGS_ORGANIZATION,
    )

    assert _sandbox is not None
    # Ten sam magazyn co ``default_qsettings()`` w programie (bez poprawek testu).
    real = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    location = Path(real.fileName()).resolve()
    assert _sandbox.resolve() in location.parents, location


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if collection_path == E2E_DIR and not config.getoption("--e2e"):
        return True
    return None


@pytest.fixture(scope="session")
def qapp_cls():
    """Ta sama klasa aplikacji co w programie (``LC_NUMERIC=C`` dla FFmpeg)."""
    from transkryptor.ui.application import Application

    return Application


@pytest.fixture(autouse=True)
def polish_ui_language():
    """Testy sprawdzają polskie teksty - niezależnie od języka systemu."""
    i18n.set_language(i18n.POLISH)
    yield
    i18n.set_language(i18n.POLISH)


@pytest.fixture(autouse=True)
def no_cuda(monkeypatch):
    """Testy nie zależą od karty graficznej komputera, na którym biegną."""
    monkeypatch.setattr("transkryptor.asr.engine.cuda_device_count", lambda: 0)
