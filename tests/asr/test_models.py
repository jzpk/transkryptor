"""Testy metadanych modelu ASR i lokalizacji katalogu modeli."""

from pathlib import Path

import pytest

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


@pytest.mark.parametrize("model", models.MODELS, ids=lambda model: model.key)
def test_model_files_cover_runtime(model: models.AsrModelInfo) -> None:
    names = {file.name for file in model.files}
    assert {"model.bin", "tokenizer.json", "config.json"} <= names
    assert names & {"vocabulary.txt", "vocabulary.json"}
    assert model.license_id == "MIT"
    assert model.hf_repo_id.startswith("Systran/faster-whisper-")
    assert model.source_url.endswith(model.hf_repo_id)
    assert model.min_ram_bytes > 0


def test_registry_keys_are_unique_and_include_default() -> None:
    keys = [model.key for model in models.MODELS]
    assert keys == ["small", "medium", "large-v3"]
    assert models.DEFAULT_MODEL in models.MODELS


def test_model_by_key_falls_back_to_default() -> None:
    assert models.model_by_key("large-v3") is models.WHISPER_LARGE_V3
    assert models.model_by_key("small") is models.WHISPER_SMALL
    assert models.model_by_key("nieznany") is models.DEFAULT_MODEL


def test_models_root_respects_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = models.default_models_root()
    assert root == Path(tmp_path) / "transkryptor" / "models"


def test_format_size() -> None:
    assert models.format_size(1_500_000_000) == "1.5 GB"
    assert models.format_size(242_000_000) == "242 MB"
