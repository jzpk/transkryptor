"""Przebieg „sprawdź → pobierz” z jednym wynikiem dla warstwy UI.

Kolejność:

1. Wynik zapytania z tej doby wskazuje nowszą wersję → bez nowego zapytania
   (ponowienie pobrania nie zużywa limitu API).
2. W przeciwnym razie rezerwacja zapytania w dziennym limicie i jedno
   zapytanie do API. Brak sieci zwraca rezerwację — limit liczy tylko
   zapytania, które dotarły do serwera.
3. Nowsza wersja w artefakcie wydania → pobranie i weryfikacja; w środowisku
   deweloperskim → tylko informacja z linkiem do strony wydania.

Serwis jest synchroniczny; wątek tła zapewnia ``ui/update_controller.py``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

import httpx

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.update.download import (
    DownloadCancelled,
    clear_downloads,
    download_release,
)
from transkryptor.update.install import can_self_update
from transkryptor.update.quota import RequestQuota
from transkryptor.update.releases import (
    USER_AGENT,
    ReleaseInfo,
    current_platform,
    fetch_latest,
    is_newer,
)

# Krótki limit na nawiązanie połączenia (start nie czeka na wolną sieć),
# dłuższy na odczyt kolejnych porcji pobieranego artefaktu.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class UpdateStatus(Enum):
    UP_TO_DATE = "up_to_date"
    READY = "ready"  # nowa wersja pobrana i zweryfikowana
    AVAILABLE = "available"  # nowa wersja jest, ale bez samoaktualizacji
    QUOTA_EXHAUSTED = "quota_exhausted"
    OFFLINE = "offline"
    ERROR = "error"
    CANCELLED = "cancelled"  # aplikacja zamknięta w trakcie pobierania


@dataclass(frozen=True)
class UpdateOutcome:
    status: UpdateStatus
    release: ReleaseInfo | None = None
    artifact: Path | None = None
    error: UpdateError | None = None


def default_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    )


class UpdateService:
    """Sprawdza najnowsze wydanie i pobiera je, gdy to możliwe."""

    def __init__(
        self,
        *,
        current_version: str = __version__,
        quota: RequestQuota | None = None,
        download_root: Path | None = None,
        client_factory: Callable[[], httpx.Client] = default_client,
        platform: str = sys.platform,
        self_update: bool | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.current_version = current_version
        self.quota = quota or RequestQuota()
        self._download_root = download_root
        self._client_factory = client_factory
        self._platform = current_platform(platform)
        self._self_update = (
            can_self_update(platform=platform) if self_update is None else self_update
        )
        self._today = today

    def run(self, should_cancel: Callable[[], bool] = lambda: False) -> UpdateOutcome:
        today = self._today()
        with self._client_factory() as client:
            release = self.quota.cached_release(today)
            if release is None or not is_newer(release.version, self.current_version):
                if not self.quota.try_acquire(today):
                    return UpdateOutcome(UpdateStatus.QUOTA_EXHAUSTED)
                try:
                    release = fetch_latest(client, self._platform)
                except httpx.TransportError:
                    self.quota.refund(today)
                    return UpdateOutcome(UpdateStatus.OFFLINE)
                except UpdateError as error:
                    return UpdateOutcome(UpdateStatus.ERROR, error=error)
                self.quota.remember(today, release)

            if release is None or not is_newer(release.version, self.current_version):
                if self._self_update:
                    clear_downloads(self._download_root)
                return UpdateOutcome(UpdateStatus.UP_TO_DATE, release)
            if not self._self_update or release.artifact is None:
                return UpdateOutcome(UpdateStatus.AVAILABLE, release)

            try:
                artifact = download_release(
                    release, client, self._download_root, should_cancel
                )
            except DownloadCancelled:
                return UpdateOutcome(UpdateStatus.CANCELLED, release)
            except httpx.TransportError:
                return UpdateOutcome(UpdateStatus.OFFLINE, release)
            except (UpdateError, OSError) as error:
                failure = (
                    error
                    if isinstance(error, UpdateError)
                    else UpdateError(
                        user_message=f"Nie udało się zapisać aktualizacji: {error}"
                    )
                )
                return UpdateOutcome(UpdateStatus.ERROR, release, error=failure)
            return UpdateOutcome(UpdateStatus.READY, release, artifact)
