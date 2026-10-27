"""Granice warstw: logika domenowa bez Qt, interfejs tylko z ``ui`` i wejścia.

Test czyta importy z drzewa składni (bez importowania modułów), więc
sprawdza też importy wewnątrz funkcji i bloków ``TYPE_CHECKING``.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path("src/transkryptor")

# Pakiety i moduły bez zależności od Qt: działają w procesie roboczym ASR,
# w skryptach budowania i w testach bez wyświetlacza.
QT_FREE = (
    "asr",
    "corpus",
    "document",
    "notation",
    "update",
    "changes.py",
    "errors.py",
    "feedback.py",
    "fileio.py",
    "paths.py",
    "settings.py",
)

# Jedyne moduły spoza ``ui``, które mogą importować interfejs.
UI_ENTRY_POINTS = ("__main__.py",)


def _modules(*names: str) -> list[Path]:
    paths: list[Path] = []
    for name in names:
        target = PACKAGE / name
        paths.extend(sorted(target.rglob("*.py")) if target.is_dir() else [target])
    return paths


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


@pytest.mark.parametrize("path", _modules(*QT_FREE), ids=_relative)
def test_domain_does_not_import_qt_or_ui(path: Path) -> None:
    forbidden = {
        name
        for name in _imports(path)
        if name.split(".")[0] == "PySide6" or name.startswith("transkryptor.ui")
    }
    assert not forbidden


def test_only_entry_points_import_ui() -> None:
    offenders = [
        _relative(path)
        for path in sorted(PACKAGE.rglob("*.py"))
        if _relative(path).split("/")[0] != "ui"
        and _relative(path) not in UI_ENTRY_POINTS
        and any(name.startswith("transkryptor.ui") for name in _imports(path))
    ]
    assert offenders == []
