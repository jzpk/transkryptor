"""Konfiguracja testów end-to-end: prawdziwe okno programu i pliki wzorcowe.

Testy e2e przechodzą całe ścieżki pracy przez ``MainWindow`` (offscreen),
na prawdziwych plikach - nagraniu z ``tests/fixtures`` i plikach zapisanych
poprzednimi wersjami programu (``data/``). Wyniki porównują z plikami
wzorcowymi w ``golden/``: każda zmiana formatu wyjścia musi być świadoma.
Po zamierzonej zmianie wzorce odświeża ``pytest --e2e --update-golden``,
a różnicę ogląda się w ``git diff`` przed commitem.

Izolację od danych użytkownika i atrapy dialogów biorą z testów UI.
"""

import difflib
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.ui.conftest import (  # noqa: F401 - fikstury dla testów e2e
    add_window,
    enough_memory,
    isolated_autosave,
    isolated_playback_cache,
    isolated_rules,
    isolated_settings,
    isolated_waveform_cache,
    no_blocking_dialogs,
)

E2E_DIR = Path(__file__).parent
DATA_DIR = E2E_DIR / "data"
GOLDEN_DIR = E2E_DIR / "golden"
REPO_ROOT = E2E_DIR.parent.parent

Golden = Callable[[str, str], None]


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    """Porównuje tekst z plikiem ``golden/<nazwa>`` (z ``--update-golden`` zapisuje)."""
    update = request.config.getoption("--update-golden")

    def check(name: str, actual: str) -> None:
        path = GOLDEN_DIR / name
        if update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8", newline="\n")
            return
        if not path.is_file():
            pytest.fail(f"brak wzorca {name} - uruchom pytest --e2e --update-golden")
        expected = path.read_text(encoding="utf-8")
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    f"golden/{name}",
                    "wynik",
                )
            )
            pytest.fail(
                f"wynik różni się od wzorca {name} (zamierzona zmiana: "
                f"pytest --e2e --update-golden):\n{diff}",
                pytrace=False,
            )

    return check
