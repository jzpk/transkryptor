"""Przebieg „sprawdź → pobierz” z jednym wynikiem dla warstwy UI.

Kolejność:

1. Pobranie podpisu najnowszego wydania (kilkaset bajtów, bez API GitHuba
   i jego limitu) i odczyt wersji z zaufanego komentarza.
2. Nowsza wersja → pobranie i weryfikacja artefaktu; w środowisku
   deweloperskim → tylko informacja o nowej wersji.

Przy okazji każdego sprawdzenia przebieg odczytuje też podpisane ostrzeżenie
o wersjach z lukami (``update/advisory.py``); wynik niesie je tylko wtedy,
gdy dotyczy bieżącej wersji. Ostrzeżenie działa także bez sieci (lokalna
kopia) i nigdy nie zmienia statusu przebiegu.

Przebieg nie ma stanu między uruchomieniami, więc może się powtarzać
dowolnie często (start i okresowe sprawdzenie w ``ui/update_controller.py``).

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


class UpdateStage(Enum):
    """Etap przebiegu zgłaszany warstwie UI (ekran startowy)."""

    CHECKING = "checking"
    DOWNLOADING = "downloading"


StageCallback = Callable[[UpdateStage, ReleaseInfo | None], None]


class UpdateStatus(Enum):
    UP_TO_DATE = "up_to_date"
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
    """Sprawdza najnowsze wydanie i pobiera je, gdy to możliwe."""

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

    def run(
        self,
        should_cancel: Callable[[], bool] = lambda: False,
        on_progress: DownloadProgress | None = None,
        on_stage: StageCallback | None = None,
    ) -> UpdateOutcome:
        """Jeden przebieg; ``on_stage`` i ``on_progress`` zasilają ekran startowy."""
        stage = on_stage or (lambda _stage, _release: None)
        stage(UpdateStage.CHECKING, None)
        with self._client_factory() as client:
            advisory = current_advisory(client, self._advisory_store)
            if advisory is not None and not advisory.applies_to(self.current_version):
                advisory = None
            outcome = self._check_and_download(
                client, should_cancel, on_progress, stage
            )
        return replace(outcome, advisory=advisory)

    def _check_and_download(
        self,
        client: httpx.Client,
        should_cancel: Callable[[], bool],
        on_progress: DownloadProgress | None,
        stage: StageCallback,
    ) -> UpdateOutcome:
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

        stage(UpdateStage.DOWNLOADING, release)
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
