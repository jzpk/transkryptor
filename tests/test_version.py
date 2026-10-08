"""Wersja ma jedno znaczenie: pyproject.toml i ``transkryptor.__version__``.

Workflow wydania podbija obie wartości naraz; rozjazd oznaczałby artefakt
z inną wersją niż tag, a aplikacja porównywałaby się z wydaniami błędnie.
"""

import tomllib
from pathlib import Path

from transkryptor import __version__
from transkryptor.update.releases import parse_version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_package_version_matches_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__


def test_version_is_plain_semver() -> None:
    """Aktualizacje porównują wersje w postaci X.Y.Z."""
    assert parse_version(__version__) is not None
