"""Plik projektu ``.transkr``: stan pracy nad nagraniem (bez Qt).

Projekt to jeden plik JSON (UTF-8) z polem ``schema_version``. Zawiera
tekst z zakresami indeksu górnego, autora, datę i metryczkę, odwołanie do
nagrania (ścieżka względna do pliku projektu, bezwzględna jako podpowiedź
i suma SHA-256 - bez osadzania audio), pozycję odtwarzania, pętlę A-B,
ostatni wynik ASR (tekst i segmenty z czasami i pewnością) oraz pozycje
przeglądu reguł (zakres w tekście, kod reguły i treść propozycji), a od
schematu 2 także kontekst nagrania i słownik projektu dla ASR, od
schematu 3 - ostrzeżenia walidatora zignorowane w konkretnych miejscach,
od schematu 4 - kotwice czasowe tekstu (``document/anchors.py``), od
schematu 5 - mówcy nagrania, ich przypisanie do akapitów
(``document/speakers.py``) i mówcy segmentów ASR z podziału na mówców, a od
schematu 6 - komentarze recenzji z odpowiedziami i statusem rozwiązania
(``document/comments.py``; pole ``resolved`` jest opcjonalne) i sprawdzone zakresy nagrania (``document/verification.py``).

Zapis jest atomowy (``transkryptor.fileio.write_atomic``) - przerwany
zapis nie psuje poprzedniej wersji. Odczyt przechodzi przez :func:`migrate`,
który podnosi starsze schematy do bieżącego.

Moduły pakietu: ``model`` (dataclassy stanu), ``codec`` (JSON i walidacja
pól), ``migrations`` (schematy), ``paths`` (odwołanie do nagrania)
i ``storage`` (zapis i odczyt pliku). Pakiet re-eksportuje ich publiczne
nazwy.
"""

from transkryptor.document.project.codec import dumps, from_dict, loads, to_dict
from transkryptor.document.project.errors import InvalidProjectError
from transkryptor.document.project.migrations import SCHEMA_VERSION, migrate
from transkryptor.document.project.model import (
    PROJECT_SUFFIX,
    AsrContext,
    AsrDraft,
    AsrSegment,
    AsrWord,
    AudioRef,
    IgnoredWarning,
    PlayerState,
    ProjectState,
    ReviewEntry,
    file_dialog_filter,
)
from transkryptor.document.project.paths import (
    audio_ref,
    relative_audio_path,
    resolve_audio,
)
from transkryptor.document.project.storage import load_project, save_project

__all__ = [
    "PROJECT_SUFFIX",
    "SCHEMA_VERSION",
    "AsrContext",
    "AsrDraft",
    "AsrSegment",
    "AsrWord",
    "AudioRef",
    "IgnoredWarning",
    "InvalidProjectError",
    "PlayerState",
    "ProjectState",
    "ReviewEntry",
    "audio_ref",
    "dumps",
    "file_dialog_filter",
    "from_dict",
    "load_project",
    "loads",
    "migrate",
    "relative_audio_path",
    "resolve_audio",
    "save_project",
    "to_dict",
]
