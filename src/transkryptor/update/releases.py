"""Najnowsze wydanie z plików wydania GitHub i porównanie wersji.

Sprawdzenie nie korzysta z REST API GitHuba (limit 60 zapytań na godzinę
z jednego adresu IP, wspólny dla instalacji w sieci instytucji). Adres
``releases/latest/download/<plik>`` przekierowuje do pliku z najnowszego
wydania - pobierany jest tylko podpis sum kontrolnych (kilkaset bajtów),
a wersję wydania podaje jego zaufany komentarz potwierdzony kluczem wydań
(``signature.verify_comment``). Pozostałe pliki mają stałe adresy
``releases/download/v<wersja>/<plik>``.

Zapytanie zawiera wyłącznie standardowe nagłówki HTTP (``User-Agent``
z wersją aplikacji) - bez identyfikatora instalacji i bez telemetrii.
Wydania wstępne i szkice nie są „najnowsze”, więc nie trafiają do aktualizacji.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.fileio import SizeLimitError, limited_chunks
from transkryptor.i18n import tr
from transkryptor.update.signature import (
    SignatureError,
    verify_comment,
    version_from_comment,
)

# Jedyne miejsce z adresem repozytorium. GitHub przekierowuje stare adresy po
# zmianie nazwy, a klient podąża za przekierowaniami.
GITHUB_REPO = "jzpk/transkryptor"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
USER_AGENT = f"Transkryptor/{__version__}"

CHECKSUMS_ASSET = "SHA256SUMS.txt"
SIGNATURE_ASSET = f"{CHECKSUMS_ASSET}.minisig"
LATEST_SIGNATURE_URL = f"{RELEASES_URL}/latest/download/{SIGNATURE_ASSET}"
# Hosty, z którymi klient aktualizacji w ogóle rozmawia: github.com i hosty,
# na które GitHub przekierowuje pobranie plików wydania.
UPDATE_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
# Sufiksy nazw artefaktów z ``packaging.metadata.targets`` (zgodność pilnuje
# test; kod uruchomieniowy nie importuje narzędzia wydania).
ASSET_SUFFIXES = {
    "windows": "-windows-x64-setup.exe",
    "linux": "-x86_64.AppImage",
}
# Podpis i sumy mają po kilkaset bajtów; limit chroni pamięć przed
# nieskończoną odpowiedzią serwera.
MAX_SMALL_FILE_BYTES = 64 * 1024

Version = tuple[int, int, int]
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> Version | None:
    """``"v1.2.3"`` / ``"1.2.3"`` → ``(1, 2, 3)``; inny zapis → None."""
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def is_newer(candidate: str, current: str = __version__) -> bool:
    """Czy ``candidate`` jest nowszą wersją niż ``current``."""
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def is_safe_asset_name(name: str) -> bool:
    """Sama nazwa pliku: bez katalogów, separatorów i nazw specjalnych."""
    return (
        bool(name)
        and name not in {".", ".."}
        and not any(char in name for char in "/\\\0:")
    )


def check_request_host(request: httpx.Request) -> None:
    """Hak żądań klienta aktualizacji: tylko ``https`` na ``UPDATE_HOSTS``.

    Klient podąża za przekierowaniami, a hak widzi każde żądanie, także
    przekierowane - adres spoza listy kończy się ``UpdateError``, zanim
    cokolwiek zostanie pobrane. Autentyczność plików i tak potwierdza podpis.
    """
    if request.url.scheme != "https" or request.url.host not in UPDATE_HOSTS:
        raise UpdateError(
            user_message=tr("update.error.host", host=request.url.host),
            retry_hint=tr("update.error.later.hint"),
        )


def current_platform(platform: str = sys.platform) -> str | None:
    """Klucz platformy wydania (``windows``/``linux``) albo None."""
    if platform.startswith("win"):
        return "windows"
    if platform.startswith("linux"):
        return "linux"
    return None


@dataclass(frozen=True)
class ReleaseInfo:
    """Najnowsze wydanie widziane z bieżącej platformy.

    ``signature`` to treść ``SHA256SUMS.txt.minisig``, której zaufany
    komentarz wskazał ``version``; pobranie sprawdza nią sumy kontrolne.
    """

    version: str
    signature: str
    platform: str | None = None

    def __post_init__(self) -> None:
        # Wersja trafia do adresów i ścieżki katalogu pobrań - tylko X.Y.Z.
        parsed = parse_version(self.version)
        if parsed is None or ".".join(map(str, parsed)) != self.version:
            raise ValueError(f"niepoprawna wersja wydania: {self.version!r}")

    @property
    def page_url(self) -> str:
        return f"{RELEASES_URL}/tag/v{self.version}"

    @property
    def artifact_suffix(self) -> str | None:
        """Końcówka nazwy artefaktu dla platformy (None: brak samoaktualizacji)."""
        return ASSET_SUFFIXES.get(self.platform or "")

    def asset_url(self, name: str) -> str:
        if not is_safe_asset_name(name):
            raise ValueError(f"niebezpieczna nazwa pliku wydania: {name!r}")
        return f"{RELEASES_URL}/download/v{self.version}/{name}"


def fetch_small(client: httpx.Client, url: str) -> httpx.Response | bytes:
    """Mały plik wydania: treść albo odpowiedź z kodem innym niż 200.

    Odczyt jest strumieniowy z limitem ``MAX_SMALL_FILE_BYTES`` - plik nie
    trafia w całości do pamięci, zanim podpis go odrzuci. Błędy połączenia
    (``httpx.TransportError``) przechodzą bez zmian.
    """
    with client.stream("GET", url) as response:
        if response.status_code != 200:
            return response
        # Porcje takie, jak przychodzą z sieci - bez buforowania 1 MB naraz.
        try:
            return b"".join(limited_chunks(response.iter_bytes(), MAX_SMALL_FILE_BYTES))
        except SizeLimitError as error:
            raise too_large(url.rsplit("/", 1)[-1]) from error


def too_large(name: str) -> UpdateError:
    return UpdateError(
        user_message=tr("update.error.too_large", name=name),
        retry_hint=tr("update.error.later.hint"),
    )


def fetch_latest(
    client: httpx.Client,
    platform: str | None,
    trusted_keys: Iterable[str] | None = None,
) -> ReleaseInfo | None:
    """Jedno pobranie podpisu najnowszego wydania i odczyt jego wersji.

    Zwraca None, gdy repozytorium nie ma jeszcze żadnego wydania (404).
    Błędy połączenia (``httpx.TransportError``) przechodzą bez zmian - wołający
    odróżnia brak sieci od błędnej odpowiedzi serwera (``UpdateError``).
    ``trusted_keys=None`` oznacza klucze wbudowane w aplikację.
    """
    result = fetch_small(client, LATEST_SIGNATURE_URL)
    if isinstance(result, httpx.Response):
        if result.status_code == 404:
            return None
        raise UpdateError(
            user_message=tr("update.error.server", status=result.status_code),
            retry_hint=tr("update.error.later.hint"),
        )
    signature = result.decode("utf-8", "replace")
    try:
        version = version_from_comment(verify_comment(signature, trusted_keys))
        return ReleaseInfo(version, signature, platform)
    except (SignatureError, ValueError) as error:
        raise UpdateError(
            user_message=tr("update.error.latest_signature"),
            retry_hint=tr("update.error.later.hint"),
        ) from error
