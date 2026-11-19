"""Sprawdzenie i pobranie aktualizacji - dwa osobne kroki dla warstwy UI.

1. :meth:`UpdateService.check` pobiera podpis najnowszego wydania (kilkaset
   bajtów, bez API GitHuba i jego limitu) i odczytuje wersję z zaufanego
   komentarza. Nic więcej nie jest pobierane.
2. :meth:`UpdateService.download` pobiera i weryfikuje artefakt - dopiero
   na wyraźne polecenie użytkownika („Pobierz i zainstaluj”). W środowisku
   deweloperskim sprawdzenie zwraca tylko informację o nowej wersji.

Przy okazji każdego sprawdzenia serwis odczytuje też podpisane ostrzeżenie
o wersjach z lukami (``update/advisory.py``); wynik niesie je tylko wtedy,
gdy dotyczy bieżącej wersji. Ostrzeżenie działa także bez sieci (lokalna
kopia) i nigdy nie zmienia statusu sprawdzenia.

Kroki nie mają stanu między uruchomieniami, więc sprawdzenie może się
powtarzać dowolnie często (start i okresowe sprawdzenie w
``ui/update_controller.py``).

Serwis jest synchroniczny; wątek tła zapewnia ``ui/update_controller.py``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

import httpx

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.i18n import tr
from transkryptor.net import DownloadCancelled, make_client
from transkryptor.update.advisory import Advisory, AdvisoryStore, current_advisory
from transkryptor.update.download import (
    DownloadProgress,
    clear_downloads,
    download_release,
)
from transkryptor.update.install import can_self_update
from transkryptor.update.releases import (
    ReleaseInfo,
    check_request_host,
    current_platform,
    fetch_latest,
    is_newer,
)

# Krótki limit na nawiązanie połączenia (start nie czeka na wolną sieć),
# dłuższy na odczyt kolejnych porcji pobieranego artefaktu.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class UpdateStatus(Enum):
    UP_TO_DATE = "up_to_date"
    DOWNLOADABLE = "downloadable"  # nowa wersja czeka na zgodę na pobranie
    READY = "ready"  # nowa wersja pobrana i zweryfikowana
    AVAILABLE = "available"  # nowa wersja jest, ale bez samoaktualizacji
    OFFLINE = "offline"
    ERROR = "error"
    CANCELLED = "cancelled"  # aplikacja zamknięta w trakcie pobierania


@dataclass(frozen=True)
class UpdateOutcome:
    status: UpdateStatus
    release: ReleaseInfo | None = None
    artifact: Path | None = None
    error: UpdateError | None = None
    # Ostrzeżenie o luce dotyczące bieżącej wersji (``update/advisory.py``).
    advisory: Advisory | None = None


def default_client() -> httpx.Client:
    return make_client(check_request_host, timeout=TIMEOUT)


class UpdateService:
    """Sprawdza najnowsze wydanie i pobiera je na żądanie."""

    def __init__(
        self,
        *,
        current_version: str = __version__,
        download_root: Path | None = None,
        client_factory: Callable[[], httpx.Client] = default_client,
        platform: str = sys.platform,
        self_update: bool | None = None,
        advisory_store: AdvisoryStore | None = None,
    ) -> None:
        self.current_version = current_version
        self._advisory_store = advisory_store or AdvisoryStore()
        self._download_root = download_root
        self._client_factory = client_factory
        self._platform = current_platform(platform)
        self._self_update = (
            can_self_update(platform=platform) if self_update is None else self_update
        )

    def check(self) -> UpdateOutcome:
        """Tylko sprawdzenie wersji - bez pobierania artefaktu."""
        with self._client_factory() as client:
            advisory = current_advisory(client, self._advisory_store)
            outcome = self._check_latest(client)
        if advisory is not None and advisory.applies_to(self.current_version):
            return replace(outcome, advisory=advisory)
        return outcome

    def _check_latest(self, client: httpx.Client) -> UpdateOutcome:
        try:
            release = fetch_latest(client, self._platform)
        except httpx.TransportError:
            return UpdateOutcome(UpdateStatus.OFFLINE)
        except UpdateError as error:
            return UpdateOutcome(UpdateStatus.ERROR, error=error)

        if release is None or not is_newer(release.version, self.current_version):
            if self._self_update:
                clear_downloads(self._download_root)
            return UpdateOutcome(UpdateStatus.UP_TO_DATE, release)
        if not self._self_update or release.artifact_suffix is None:
            return UpdateOutcome(UpdateStatus.AVAILABLE, release)
        return UpdateOutcome(UpdateStatus.DOWNLOADABLE, release)

    def download(
        self,
        release: ReleaseInfo,
        should_cancel: Callable[[], bool] = lambda: False,
        on_progress: DownloadProgress | None = None,
    ) -> UpdateOutcome:
        """Pobranie i weryfikacja wydania wskazanego przez :meth:`check`."""
        with self._client_factory() as client:
            try:
                artifact = download_release(
                    release,
                    client,
                    self._download_root,
                    should_cancel,
                    on_progress=on_progress,
                )
            except DownloadCancelled:
                return UpdateOutcome(UpdateStatus.CANCELLED, release)
            except httpx.TransportError:
                return UpdateOutcome(UpdateStatus.OFFLINE, release)
            except (UpdateError, OSError) as error:
                failure = (
                    error
                    if isinstance(error, UpdateError)
                    else UpdateError(user_message=tr("update.error.save", reason=error))
                )
                return UpdateOutcome(UpdateStatus.ERROR, release, error=failure)
        return UpdateOutcome(UpdateStatus.READY, release, artifact)
