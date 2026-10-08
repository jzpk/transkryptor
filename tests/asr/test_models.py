"""Testy metadanych modelu ASR i lokalizacji katalogu modeli."""

from pathlib import Path

from transkryptor.asr import models


def test_default_model_metadata_is_complete() -> None:
    model = models.DEFAULT_MODEL
    assert model.display_name
    assert model.hf_repo_id == "Systran/faster-whisper-medium"
    assert model.license_id == "MIT"
    assert model.approx_size_bytes > 0
    assert model.min_ram_bytes > 0
    assert model.source_url.startswith("https://huggingface.co/")
    assert model.description


def test_required_files_cover_runtime() -> None:
    assert "model.bin" in models.REQUIRED_FILES
    assert "tokenizer.json" in models.REQUIRED_FILES
    assert "config.json" in models.REQUIRED_FILES


def test_models_root_respects_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = models.default_models_root()
    assert root == Path(tmp_path) / "transkryptor" / "models"


def test_format_size() -> None:
    assert models.format_size(1_500_000_000) == "1.5 GB"
    assert models.format_size(242_000_000) == "242 MB"
