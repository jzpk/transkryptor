"""Limity rozmiaru modułów i funkcji z ``CLAUDE.md`` (moduł ~500 linii).

Moduły i funkcje, które już przekraczają limit, są na listach wyjątków
z obecnym rozmiarem jako górną granicą: mogą się tylko zmniejszać. Przy
podziale modułu obniż albo usuń jego wpis - test przypomina o tym, gdy
moduł zmieścił się w limicie.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "transkryptor"
MODULE_LIMIT = 500
FUNCTION_LIMIT = 100

# Moduł → największa dozwolona liczba linii (do stopniowego skracania).
MODULE_EXCEPTIONS = {
    "settings.py": 608,
    "ui/asr_transcription_section.py": 681,
    "ui/corpus_dialog.py": 862,
    "ui/editor.py": 678,
    "ui/main_window.py": 1119,
    "ui/player_bar.py": 630,
    "ui/session.py": 528,
    "ui/settings_pages.py": 518,
    "ui/sync_controller.py": 506,
    "ui/theme.py": 698,
}

# Funkcja (moduł::nazwa) → największa dozwolona liczba linii.
FUNCTION_EXCEPTIONS = {
    "document/project/codec.py::_parse": 170,
    "packaging/release_notes.py::render_release_notes": 148,
    "ui/rules_editor.py::__init__": 128,
    "ui/search_bar.py::__init__": 110,
    "ui/theme.py::stylesheet": 440,
}


def _modules() -> list[tuple[str, str]]:
    return [
        (path.relative_to(PACKAGE).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(PACKAGE.rglob("*.py"))
    ]


def test_modules_stay_within_the_size_limit() -> None:
    too_long = []
    for name, text in _modules():
        lines = len(text.splitlines())
        limit = MODULE_EXCEPTIONS.get(name, MODULE_LIMIT)
        if lines > limit:
            too_long.append(f"{name}: {lines} > {limit}")
    assert not too_long, "Podziel moduł zamiast go wydłużać:\n" + "\n".join(too_long)


def test_functions_stay_within_the_size_limit() -> None:
    too_long = []
    for name, text in _modules():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                key = f"{name}::{node.name}"
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                limit = FUNCTION_EXCEPTIONS.get(key, FUNCTION_LIMIT)
                if length > limit:
                    too_long.append(f"{key}: {length} > {limit}")
    assert not too_long, "Podziel funkcję na etapy:\n" + "\n".join(too_long)


def test_exceptions_are_lowered_after_a_split() -> None:
    sizes = {name: len(text.splitlines()) for name, text in _modules()}
    stale = [
        f"{name}: {sizes.get(name, 0)} (wpis {limit})"
        for name, limit in MODULE_EXCEPTIONS.items()
        if sizes.get(name, 0) < limit
    ]
    assert not stale, "Obniż albo usuń wpis w MODULE_EXCEPTIONS:\n" + "\n".join(stale)
