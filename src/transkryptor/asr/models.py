"""Rejestr modeli ASR oraz lokalizacja katalogu modeli.

Decyzja modelowa fazy 04 (uzasadnienie: ``docs/asr-model-decision.md``):
silnik faster-whisper (CTranslate2, MIT) z modelem Whisper medium w konwersji
CT2 z repozytorium ``Systran/faster-whisper-medium`` (model: MIT, kod: MIT).
Faza 09 dodała do wyboru warianty ``small`` i ``large-v3`` z oficjalnych
konwersji Systran (MIT); domyślnym modelem pozostaje ``medium``.

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
    """Plik modelu z oczekiwanym rozmiarem i sumą SHA-256 (szesnastkowo).

    ``repo_id`` i ``revision`` nadpisują repozytorium i rewizję modelu, gdy
    plik pochodzi z innego repozytorium (model mówców składa się z dwóch).
    """

    name: str
    size: int
    sha256: str
    repo_id: str | None = None
    revision: str | None = None


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

# Rewizje, rozmiary i sumy odczytane z repozytoriów modeli (2026-10-11;
# commity z 2023-11-23). Minimum RAM dla small i large-v3 to oszacowanie
# proporcjonalne do pomiaru medium — pomiar w fazie 15.
_WHISPER_SMALL_FILES = (
    ModelFile(
        "config.json",
        2_370,
        "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
    ),
    ModelFile(
        "model.bin",
        483_546_902,
        "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
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

WHISPER_SMALL = AsrModelInfo(
    key="small",
    display_name="Whisper small (faster-whisper, CTranslate2)",
    hf_repo_id="Systran/faster-whisper-small",
    hf_revision="536b0662742c02347bc0e980a01041f333bce120",
    files=_WHISPER_SMALL_FILES,
    approx_size_bytes=sum(file.size for file in _WHISPER_SMALL_FILES),
    license_id="MIT",
    source_url="https://huggingface.co/Systran/faster-whisper-small",
    min_ram_bytes=2_000_000_000,
    description=(
        "Mniejszy wariant Whispera: około trzy razy szybszy od medium i mniej "
        "wymagający, kosztem większej liczby błędów w szkicu. Dla słabszych "
        "komputerów."
    ),
)

_WHISPER_LARGE_V3_FILES = (
    ModelFile(
        "config.json",
        2_394,
        "a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9",
    ),
    ModelFile(
        "model.bin",
        3_087_284_237,
        "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
    ),
    ModelFile(
        "preprocessor_config.json",
        340,
        "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711",
    ),
    ModelFile(
        "tokenizer.json",
        2_480_617,
        "6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca",
    ),
    ModelFile(
        "vocabulary.json",
        1_068_114,
        "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1",
    ),
)

WHISPER_LARGE_V3 = AsrModelInfo(
    key="large-v3",
    display_name="Whisper large-v3 (faster-whisper, CTranslate2)",
    hf_repo_id="Systran/faster-whisper-large-v3",
    hf_revision="edaa852ec7e145841d8ffdb056a99866b5f0a478",
    files=_WHISPER_LARGE_V3_FILES,
    approx_size_bytes=sum(file.size for file in _WHISPER_LARGE_V3_FILES),
    license_id="MIT",
    source_url="https://huggingface.co/Systran/faster-whisper-large-v3",
    min_ram_bytes=6_000_000_000,
    description=(
        "Największy wariant Whispera: najlepsza jakość, ale około dwa razy "
        "wolniejszy od medium na CPU i wymagający więcej pamięci. Zalecany "
        "z kartą graficzną NVIDIA."
    ),
)

DEFAULT_MODEL = WHISPER_MEDIUM

# Model podziału na mówców (diaryzacja, sherpa-onnx): model głosu mówcy
# CAM++ z projektu 3D-Speaker (Apache-2.0) trenowany na ok. 200 tys.
# mówców (zh/en). Wariant VoxCeleb nie odróżniał w nagraniach terenowych
# głosu badaczki od informatorki. Rewizja, rozmiar i suma odczytane
# z repozytorium (2026-10-24; commit z 2024-10-14).
DIARIZATION_EMBEDDING_FILE = (
    "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
)
_DIARIZATION_FILES = (
    ModelFile(
        DIARIZATION_EMBEDDING_FILE,
        28_281_164,
        "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2",
    ),
)

DIARIZATION_MODEL = AsrModelInfo(
    key="diarization",
    display_name="3D-Speaker CAM++ (sherpa-onnx)",
    hf_repo_id="csukuangfj/speaker-embedding-models",
    hf_revision="0743f301363dec56491a490f6d6cbc9d67f9a3bf",
    files=_DIARIZATION_FILES,
    approx_size_bytes=sum(file.size for file in _DIARIZATION_FILES),
    license_id="Apache-2.0",
    source_url="https://huggingface.co/csukuangfj/speaker-embedding-models",
    min_ram_bytes=1_000_000_000,
    description=(
        "Lokalny model podziału szkicu na mówców: rozpoznaje głosy "
        "i grupuje wypowiedzi według mówcy. Po pobraniu działa w pełni offline."
    ),
)

# Modele do wyboru w kolejności od najmniejszego (lista w panelu ASR).
MODELS: tuple[AsrModelInfo, ...] = (WHISPER_SMALL, WHISPER_MEDIUM, WHISPER_LARGE_V3)


def model_by_key(key: str) -> AsrModelInfo:
    """Model o kluczu ``key``; nieznany klucz (np. z ustawień) → domyślny."""
    for model in MODELS:
        if model.key == key:
            return model
    return DEFAULT_MODEL


def default_models_root() -> Path:
    """Katalog danych użytkownika na modele ASR (per OS, bez zmian globalnych)."""
    return user_data_dir() / "models"


def format_size(size_bytes: int) -> str:
    """Czytelny rozmiar pliku (MB/GB) do komunikatów o pobieraniu."""
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000:.0f} MB"
