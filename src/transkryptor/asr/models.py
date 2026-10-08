"""Metadane wybranego modelu ASR oraz lokalizacja katalogu modeli.

Decyzja modelowa fazy 04 (uzasadnienie: ``docs/asr-model-decision.md``):
silnik faster-whisper (CTranslate2, MIT) z modelem Whisper medium w konwersji
CT2 z repozytorium ``Systran/faster-whisper-medium`` (model: MIT, kod: MIT).

Moduł nie zależy od elementów GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transkryptor.paths import user_data_dir


@dataclass(frozen=True)
class AsrModelInfo:
    """Opis modelu ASR prezentowany użytkownikowi przed pobraniem (zgoda)."""

    key: str
    display_name: str
    hf_repo_id: str
    approx_size_bytes: int
    license_id: str
    source_url: str
    min_ram_bytes: int
    description: str


# Rozmiar odczytany z repozytorium modelu; minimum RAM wyprowadzone
# z pomiaru szczytowego zużycia pamięci — patrz docs/benchmarks-asr.md
# oraz uzasadnienie wyboru w docs/asr-model-decision.md.
WHISPER_MEDIUM = AsrModelInfo(
    key="medium",
    display_name="Whisper medium (faster-whisper, CTranslate2)",
    hf_repo_id="Systran/faster-whisper-medium",
    approx_size_bytes=1_530_575_217,
    license_id="MIT",
    source_url="https://huggingface.co/Systran/faster-whisper-medium",
    min_ram_bytes=4_000_000_000,
    description=(
        "Lokalny model rozpoznawania mowy OpenAI Whisper w wariancie medium, "
        "przekonwertowany do formatu CTranslate2. Po pobraniu działa w pełni "
        "offline. Jakość dla języka polskiego wyraźnie lepsza niż wariantów "
        "small/base przy umiarkowanym zużyciu zasobów."
    ),
)

DEFAULT_MODEL = WHISPER_MEDIUM

# Pliki, które muszą istnieć, aby model uznać za kompletny (weryfikacja
# przed uruchomieniem offline).
REQUIRED_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


def default_models_root() -> Path:
    """Katalog danych użytkownika na modele ASR (per OS, bez zmian globalnych)."""
    return user_data_dir() / "models"


def format_size(size_bytes: int) -> str:
    """Czytelny rozmiar pliku (MB/GB) do komunikatów o pobieraniu."""
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000:.0f} MB"
