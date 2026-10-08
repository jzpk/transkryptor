"""Test dymny fazy 00: pakiet jest importowalny, a punkt wejścia istnieje."""

import transkryptor
from transkryptor.__main__ import main


def test_package_has_version() -> None:
    assert transkryptor.__version__


def test_entry_point_is_callable() -> None:
    assert callable(main)


def test_module_structure_exists() -> None:
    for module in ("ui", "document", "notation", "audio", "asr", "export", "packaging"):
        __import__(f"transkryptor.{module}")
