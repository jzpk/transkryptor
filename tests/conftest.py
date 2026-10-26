"""Wspólna konfiguracja testów.

Testy end-to-end (``tests/e2e``) są zbierane tylko z opcją ``--e2e`` - zwykły
przebieg ``pytest`` (CI dla PR i main) uruchamia same testy jednostkowe
i integracyjne, a testy e2e biegną w workflow wydania.
"""

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


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--e2e"):
        return
    for arg in config.args:
        path = Path(config.invocation_params.dir, arg.split("::", 1)[0]).resolve()
        if path == E2E_DIR or E2E_DIR in path.parents:
            raise pytest.UsageError("testy e2e uruchamia: pytest --e2e tests/e2e")


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if collection_path == E2E_DIR and not config.getoption("--e2e"):
        return True
    return None


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
