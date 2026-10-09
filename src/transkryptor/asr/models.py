"""Metadane wybranego modelu ASR oraz lokalizacja katalogu modeli.

Decyzja modelowa fazy 04 (uzasadnienie: ``docs/asr-model-decision.md``):
silnik faster-whisper (CTranslate2, MIT) z modelem Whisper medium w konwersji
CT2 z repozytorium ``Systran/faster-whisper-medium`` (model: MIT, kod: MIT).

Pobierana jest przypięta rewizja repozytorium i tylko pliki z listy
``AsrModelInfo.files``, każdy weryfikowany sumą SHA-256 (SEC-02): zmiana
w repozytorium modelu nie trafi do użytkowników bez zmiany kodu.

Moduł nie zależy od elementów GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transkryptor.paths import user_data_dir


@dataclass(frozen=True)
class ModelFile:
    """Plik modelu z oczekiwanym rozmiarem i sumą SHA-256 (szesnastkowo)."""

    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AsrModelInfo:
    """Opis modelu ASR prezentowany użytkownikowi przed pobraniem (zgoda).

    ``hf_revision`` to SHA commita repozytorium, z którego pobierane są
    ``files`` — jedyne pliki zapisywane w katalogu modelu.
    """

    key: str
    display_name: str
    hf_repo_id: str
    hf_revision: str
    files: tuple[ModelFile, ...]
    approx_size_bytes: int
    license_id: str
    source_url: str
    min_ram_bytes: int
    description: str


# Rewizja, rozmiary i sumy odczytane z repozytorium modelu (2026-10-09;
# commit z 2023-11-23). Zmiana modelu = nowa rewizja i nowe sumy tutaj.
_WHISPER_MEDIUM_FILES = (
    ModelFile(
        "config.json",
        2_257,
        "3622a2ddc41ec0e0fd4e68c13c6830f03b90c38d89aaad184de02c8c642cf807",
    ),
    ModelFile(
        "model.bin",
        1_527_906_378,
        "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
    ),
    ModelFile(
        "tokenizer.json",
        2_203_239,
        "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    ),
    ModelFile(
        "vocabulary.txt",
        459_861,
        "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
    ),
)

# Minimum RAM wyprowadzone z pomiaru szczytowego zużycia pamięci — patrz
# docs/benchmarks-asr.md oraz uzasadnienie wyboru w docs/asr-model-decision.md.
WHISPER_MEDIUM = AsrModelInfo(
    key="medium",
    display_name="Whisper medium (faster-whisper, CTranslate2)",
    hf_repo_id="Systran/faster-whisper-medium",
    hf_revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
    files=_WHISPER_MEDIUM_FILES,
    approx_size_bytes=sum(file.size for file in _WHISPER_MEDIUM_FILES),
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
REQUIRED_FILES = tuple(file.name for file in DEFAULT_MODEL.files)


def default_models_root() -> Path:
    """Katalog danych użytkownika na modele ASR (per OS, bez zmian globalnych)."""
    return user_data_dir() / "models"


def format_size(size_bytes: int) -> str:
    """Czytelny rozmiar pliku (MB/GB) do komunikatów o pobieraniu."""
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000:.0f} MB"
