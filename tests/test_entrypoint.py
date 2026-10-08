"""Testy punktu wejścia: wersja i sprawdzenie kompletności artefaktu.

``--self-test`` jest narzędziem odbioru wydania (faza 05): potwierdza, że
artefakt zawiera komplet środowiska uruchomieniowego, bez otwierania okna.
"""

import io

import pytest

from transkryptor import __main__ as entrypoint
from transkryptor import __version__


@pytest.fixture(autouse=True)
def isolated_models_root(monkeypatch, tmp_path):
    """Sprawdzenie nie może zależeć od modelu pobranego na tej maszynie."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))


def test_self_test_passes_in_a_complete_environment() -> None:
    stream = io.StringIO()
    assert entrypoint.self_test(stream) == 0
    assert "Artefakt kompletny." in stream.getvalue()


def test_self_test_checks_the_whole_runtime_stack() -> None:
    stream = io.StringIO()
    entrypoint.self_test(stream)
    report = stream.getvalue()
    for module in entrypoint.REQUIRED_MODULES:
        assert f"[ok]   {module}" in report
    assert "zasób VAD" in report


def test_missing_model_is_information_not_an_error() -> None:
    """Wymaganie wydania: brak modelu nie może blokować uruchomienia."""
    stream = io.StringIO()
    assert entrypoint.self_test(stream) == 0
    assert "niepobrany (praca ręczna)" in stream.getvalue()


def test_missing_module_fails_the_check(monkeypatch) -> None:
    monkeypatch.setattr(
        entrypoint, "REQUIRED_MODULES", ("modul_ktorego_nie_ma_w_artefakcie",)
    )
    stream = io.StringIO()
    assert entrypoint.self_test(stream) == 1
    assert "BŁĄD" in stream.getvalue()


def test_missing_vad_asset_fails_the_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(entrypoint, "_vad_asset", lambda: tmp_path / "brak.onnx")
    stream = io.StringIO()
    assert entrypoint.self_test(stream) == 1
    assert "brak zasobu VAD" in stream.getvalue()


def test_self_test_is_reachable_from_the_command_line(capsys) -> None:
    assert entrypoint.main(["--self-test"]) == 0
    assert "Transkryptor" in capsys.readouterr().out


def test_version_flag_reports_the_application_version(capsys) -> None:
    with pytest.raises(SystemExit) as exit_code:
        entrypoint.main(["--version"])
    assert exit_code.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_report_survives_output_without_polish_characters() -> None:
    """Windows: wyjście w cp1252 nie zna „ę” — self-test nie może przez to paść."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    assert entrypoint.self_test(stream) == 0
    stream.flush()
    assert b"Artefakt kompletny." in raw.getvalue()
