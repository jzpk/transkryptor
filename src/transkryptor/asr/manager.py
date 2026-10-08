"""Zarządzanie lokalnym modelem ASR: stan, pobieranie, anulowanie.

Moduł nie zależy od elementów GUI. Pobieranie jest wykonywane przez
wstrzykiwany ``downloader`` — domyślnie strumieniowy odczyt z Hugging Face
z postępem bajtowym i kooperacyjnym anulowaniem; testy podstawiają imitacje.

Kompletność modelu potwierdza plik znacznika ``.complete`` zapisywany
dopiero po udanym pobraniu wszystkich wymaganych plików — przerwane
pobieranie nigdy nie jest uznawane za gotowy model.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from transkryptor.asr.models import (
    DEFAULT_MODEL,
    REQUIRED_FILES,
    AsrModelInfo,
    default_models_root,
    format_size,
)
from transkryptor.errors import ModelDownloadError

COMPLETE_MARKER = ".complete"

# Wywołanie postępu: (pobrane_bajty, całkowite_bajty lub None, nazwa_pliku).
ProgressCallback = Callable[[int, int | None, str], None]
CancelCheck = Callable[[], bool]

# Sygnatura wstrzykiwanego downloadera: pobiera repo_id do dest_dir.
Downloader = Callable[[str, Path, ProgressCallback, CancelCheck], None]


class DownloadCancelled(Exception):
    """Pobieranie przerwane na życzenie użytkownika (nie jest błędem)."""


class ModelManager:
    """Stan i instalacja lokalnego modelu ASR w katalogu danych użytkownika."""

    def __init__(
        self,
        model: AsrModelInfo = DEFAULT_MODEL,
        models_root: Path | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        self.model = model
        self._models_root = models_root or default_models_root()
        self._downloader = downloader or hf_streaming_download

    @property
    def model_dir(self) -> Path:
        """Katalog docelowy wybranego modelu."""
        return self._models_root / self.model.key

    def is_downloaded(self) -> bool:
        """Czy model jest kompletny i gotowy do pracy offline."""
        marker = self.model_dir / COMPLETE_MARKER
        return marker.is_file() and all(
            (self.model_dir / name).is_file() for name in REQUIRED_FILES
        )

    def missing_files(self) -> list[str]:
        """Lista brakujących wymaganych plików (diagnostyka stanu częściowego)."""
        return [
            name for name in REQUIRED_FILES if not (self.model_dir / name).is_file()
        ]

    def download(
        self,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> Path:
        """Pobiera model do katalogu użytkownika.

        Przy powodzeniu zwraca katalog modelu. Anulowanie zgłasza
        :class:`DownloadCancelled`, a błąd sieci lub weryfikacji —
        :class:`ModelDownloadError` ze wskazówką ponowienia (NFR-03).
        Katalog częściowy jest usuwany, aby ponowienie zaczynało czysto.
        """
        progress = on_progress or (lambda _done, _total, _name: None)
        cancel = should_cancel or (lambda: False)
        dest = self.model_dir
        dest.mkdir(parents=True, exist_ok=True)
        try:
            self._downloader(self.model.hf_repo_id, dest, progress, cancel)
        except DownloadCancelled:
            self._cleanup_partial(dest)
            raise
        except ModelDownloadError:
            self._cleanup_partial(dest)
            raise
        except Exception as error:  # noqa: BLE001 — normalizacja do AppError
            self._cleanup_partial(dest)
            raise ModelDownloadError(
                user_message=(
                    f"Nie udało się pobrać modelu {self.model.display_name}: "
                    f"{error}"
                ),
                retry_hint="Sprawdź połączenie z Internetem i spróbuj ponownie.",
            ) from error
        if cancel():
            self._cleanup_partial(dest)
            raise DownloadCancelled()
        missing = self.missing_files()
        if missing:
            self._cleanup_partial(dest)
            raise ModelDownloadError(
                user_message=(
                    "Pobranie zakończyło się, ale model jest niekompletny "
                    f"(brak: {', '.join(missing)})."
                ),
                retry_hint="Ponów pobieranie modelu.",
            )
        (dest / COMPLETE_MARKER).write_text(self.model.hf_repo_id, encoding="utf-8")
        return dest

    @staticmethod
    def _cleanup_partial(dest: Path) -> None:
        """Usuwa katalog częściowo pobranego modelu."""
        if dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)


def hf_streaming_download(
    repo_id: str,
    dest_dir: Path,
    on_progress: ProgressCallback,
    should_cancel: CancelCheck,
) -> None:
    """Domyślny downloader: strumieniowe pobieranie plików z Hugging Face.

    Lista plików i rozmiary pochodzą z API Hugging Face; każdy plik jest
    pobierany strumieniowo (httpx, zależność huggingface-hub) z postępem
    bajtowym i kooperacyjnym anulowaniem między porcjami danych.
    """
    import httpx
    from huggingface_hub import HfApi

    try:
        info = HfApi().model_info(repo_id, files_metadata=True)
    except Exception as error:  # noqa: BLE001
        raise ModelDownloadError(
            user_message=(f"Nie można pobrać informacji o modelu {repo_id}: {error}"),
            retry_hint="Sprawdź połączenie z Internetem i spróbuj ponownie.",
        ) from error
    siblings = [s for s in info.siblings or () if s.rfilename]
    total = sum(s.size or 0 for s in siblings) or None
    downloaded = 0
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        for sibling in siblings:
            if should_cancel():
                raise DownloadCancelled()
            name = sibling.rfilename
            url = f"https://huggingface.co/{repo_id}/resolve/main/{name}"
            target = dest_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with target.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=1 << 20):
                            if should_cancel():
                                raise DownloadCancelled()
                            handle.write(chunk)
                            downloaded += len(chunk)
                            on_progress(downloaded, total, name)
            except DownloadCancelled:
                raise
            except Exception as error:  # noqa: BLE001
                raise ModelDownloadError(
                    user_message=(
                        f"Nie udało się pobrać pliku „{name}” modelu: {error}"
                    ),
                    retry_hint="Sprawdź połączenie z Internetem i spróbuj ponownie.",
                ) from error


__all__ = [
    "DownloadCancelled",
    "ModelManager",
    "hf_streaming_download",
    "format_size",
]
