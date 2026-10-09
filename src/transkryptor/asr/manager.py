"""Zarządzanie lokalnym modelem ASR: stan, pobieranie, anulowanie.

Moduł nie zależy od elementów GUI. Pobieranie jest wykonywane przez
wstrzykiwany ``downloader`` — domyślnie strumieniowy odczyt z Hugging Face
z postępem bajtowym i kooperacyjnym anulowaniem; testy podstawiają imitacje.

Kompletność modelu potwierdza plik znacznika ``.complete`` zapisywany
dopiero po udanym pobraniu wszystkich wymaganych plików — przerwane
pobieranie nigdy nie jest uznawane za gotowy model.

Domyślny downloader pobiera wyłącznie pliki z ``AsrModelInfo.files``
z przypiętej rewizji i sprawdza rozmiar oraz SHA-256 każdego z nich przed
umieszczeniem go w katalogu modelu (SEC-02). Ścieżka docelowa musi leżeć
w katalogu modelu (SEC-05).
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from transkryptor.asr.models import (
    DEFAULT_MODEL,
    AsrModelInfo,
    ModelFile,
    default_models_root,
    format_size,
)
from transkryptor.errors import ModelDownloadError
from transkryptor.i18n import tr

if TYPE_CHECKING:
    import httpx

COMPLETE_MARKER = ".complete"
PARTIAL_SUFFIX = ".part"

# Wywołanie postępu: (pobrane_bajty, całkowite_bajty lub None, nazwa_pliku).
ProgressCallback = Callable[[int, int | None, str], None]
CancelCheck = Callable[[], bool]

# Sygnatura wstrzykiwanego downloadera: pobiera pliki modelu do dest_dir.
Downloader = Callable[[AsrModelInfo, Path, ProgressCallback, CancelCheck], None]


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
        return marker.is_file() and not self.missing_files()

    def missing_files(self) -> list[str]:
        """Lista brakujących wymaganych plików (diagnostyka stanu częściowego)."""
        return [
            file.name
            for file in self.model.files
            if not (self.model_dir / file.name).is_file()
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
            self._downloader(self.model, dest, progress, cancel)
        except DownloadCancelled:
            self._cleanup_partial(dest)
            raise
        except ModelDownloadError:
            self._cleanup_partial(dest)
            raise
        except Exception as error:  # noqa: BLE001 — normalizacja do AppError
            self._cleanup_partial(dest)
            raise ModelDownloadError(
                user_message=tr(
                    "asr.error.download",
                    model=self.model.display_name,
                    reason=error,
                ),
                retry_hint=tr("asr.error.network.hint"),
            ) from error
        if cancel():
            self._cleanup_partial(dest)
            raise DownloadCancelled()
        missing = self.missing_files()
        if missing:
            self._cleanup_partial(dest)
            raise ModelDownloadError(
                user_message=tr("asr.error.incomplete", missing=", ".join(missing)),
                retry_hint=tr("asr.error.incomplete.hint"),
            )
        (dest / COMPLETE_MARKER).write_text(
            f"{self.model.hf_repo_id}@{self.model.hf_revision}", encoding="utf-8"
        )
        return dest

    @staticmethod
    def _cleanup_partial(dest: Path) -> None:
        """Usuwa katalog częściowo pobranego modelu."""
        if dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)


def hf_streaming_download(
    model: AsrModelInfo,
    dest_dir: Path,
    on_progress: ProgressCallback,
    should_cancel: CancelCheck,
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Domyślny downloader: strumieniowe pobieranie plików z Hugging Face.

    Pobiera tylko ``model.files`` z rewizji ``model.hf_revision`` (bez listy
    plików z API), z postępem bajtowym i kooperacyjnym anulowaniem między
    porcjami danych. Plik trafia pod docelową nazwę dopiero po zgodności
    rozmiaru i SHA-256. ``transport`` podstawiają testy.
    """
    import httpx

    total = sum(file.size for file in model.files) or None
    downloaded = 0
    with httpx.Client(
        follow_redirects=True, timeout=60.0, transport=transport
    ) as client:
        for file in model.files:
            if should_cancel():
                raise DownloadCancelled()
            target = model_file_path(dest_dir, file.name)
            partial = target.with_name(target.name + PARTIAL_SUFFIX)
            target.parent.mkdir(parents=True, exist_ok=True)
            url = (
                f"https://huggingface.co/{model.hf_repo_id}"
                f"/resolve/{model.hf_revision}/{file.name}"
            )
            digest = hashlib.sha256()
            size = 0
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with partial.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=1 << 20):
                            if should_cancel():
                                raise DownloadCancelled()
                            handle.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                            downloaded += len(chunk)
                            on_progress(downloaded, total, file.name)
            except DownloadCancelled:
                raise
            except Exception as error:  # noqa: BLE001
                raise ModelDownloadError(
                    user_message=tr("asr.error.file", name=file.name, reason=error),
                    retry_hint=tr("asr.error.network.hint"),
                ) from error
            _verify(file, size, digest.hexdigest())
            os.replace(partial, target)


def model_file_path(dest_dir: Path, name: str) -> Path:
    """Ścieżka pliku modelu; nazwa nie może wyprowadzić poza ``dest_dir``."""
    root = dest_dir.resolve()
    target = (root / name).resolve()
    if target == root or not target.is_relative_to(root):
        raise ModelDownloadError(
            user_message=tr("asr.error.file_name", name=name),
            retry_hint=tr("asr.error.checksum.hint"),
        )
    return target


def _verify(file: ModelFile, size: int, sha256: str) -> None:
    """Rozmiar i suma pobranego pliku muszą zgadzać się z przypiętymi."""
    if size != file.size or sha256 != file.sha256:
        raise ModelDownloadError(
            user_message=tr("asr.error.checksum", name=file.name),
            retry_hint=tr("asr.error.checksum.hint"),
        )


__all__ = [
    "DownloadCancelled",
    "ModelManager",
    "hf_streaming_download",
    "model_file_path",
    "format_size",
]
