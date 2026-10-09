"""Najnowsze wydanie z GitHub Releases API i porównanie wersji.

Zapytanie zawiera wyłącznie standardowe nagłówki HTTP (``User-Agent`` z wersją
aplikacji wymaga GitHub) — bez identyfikatora instalacji i bez telemetrii.
Endpoint ``/releases/latest`` sam pomija wydania wstępne i szkice.

Dane wydania (z API albo z pliku stanu) są walidowane, zanim trafią do
ścieżek i adresów: wersja ``X.Y.Z``, nazwa pliku bez separatorów ścieżki,
adresy wyłącznie ``https`` z hostów GitHub. Autentyczność plików potwierdza
dopiero podpis sum kontrolnych (``update/signature.py``).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from transkryptor import __version__
from transkryptor.errors import UpdateError
from transkryptor.i18n import tr

# Jedyne miejsce z adresem repozytorium. GitHub przekierowuje stare adresy po
# zmianie nazwy, a klient podąża za przekierowaniami.
GITHUB_REPO = "jzpk/transkryptor"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"Transkryptor/{__version__}"

CHECKSUMS_ASSET = "SHA256SUMS.txt"
SIGNATURE_ASSET = f"{CHECKSUMS_ASSET}.minisig"
# Pliki wydań: adres z API (github.com) i hosty, na które GitHub przekierowuje.
DOWNLOAD_HOSTS = frozenset(
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


def is_safe_url(url: str, hosts: frozenset[str] = DOWNLOAD_HOSTS) -> bool:
    """Adres ``https`` na jednym z podanych hostów (bez danych logowania)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in hosts
        and parts.username is None
        and parts.password is None
    )


def safe_page_url(url: object) -> str:
    """Strona wydania do pokazania użytkownikowi; inny adres → lista wydań."""
    if isinstance(url, str) and is_safe_url(url, frozenset({"github.com"})):
        return url
    return RELEASES_PAGE_URL


def current_platform(platform: str = sys.platform) -> str | None:
    """Klucz platformy wydania (``windows``/``linux``) albo None."""
    if platform.startswith("win"):
        return "windows"
    if platform.startswith("linux"):
        return "linux"
    return None


@dataclass(frozen=True)
class Asset:
    """Plik dołączony do wydania."""

    name: str
    url: str
    size: int

    def __post_init__(self) -> None:
        if not is_safe_asset_name(self.name):
            raise ValueError(f"niebezpieczna nazwa pliku wydania: {self.name!r}")
        if not is_safe_url(self.url):
            raise ValueError(f"niedozwolony adres pliku wydania: {self.url!r}")


@dataclass(frozen=True)
class ReleaseInfo:
    """Najnowsze wydanie z plikami potrzebnymi bieżącej platformie."""

    version: str
    page_url: str
    artifact: Asset | None
    checksums: Asset | None
    signature: Asset | None = None

    def __post_init__(self) -> None:
        # Wersja trafia do ścieżki katalogu pobrań — tylko postać X.Y.Z.
        parsed = parse_version(self.version)
        if parsed is None or ".".join(map(str, parsed)) != self.version:
            raise ValueError(f"niepoprawna wersja wydania: {self.version!r}")
        if safe_page_url(self.page_url) != self.page_url:
            raise ValueError(f"niedozwolony adres strony wydania: {self.page_url!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReleaseInfo:
        """Odtwarza wydanie zapisane przez ``to_dict``.

        Błędne albo niebezpieczne dane (np. wersja ``../x``) → ValueError.
        """
        try:

            def asset(raw: object) -> Asset | None:
                if raw is None:
                    return None
                if not isinstance(raw, Mapping):
                    raise ValueError("zasób wydania nie jest słownikiem")
                return Asset(str(raw["name"]), str(raw["url"]), int(raw["size"]))

            return cls(
                version=str(data["version"]),
                page_url=str(data["page_url"]),
                artifact=asset(data.get("artifact")),
                checksums=asset(data.get("checksums")),
                signature=asset(data.get("signature")),
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"niepoprawny zapis wydania: {error}") from error


def parse_release(payload: Mapping[str, Any], platform: str | None) -> ReleaseInfo:
    """Wydanie z odpowiedzi API; brak wersji w ``tag_name`` → UpdateError."""
    tag = payload.get("tag_name")
    version = parse_version(tag) if isinstance(tag, str) else None
    if version is None:
        raise UpdateError(user_message=tr("update.error.version", tag=repr(tag)))
    assets: list[Asset] = []
    for raw in payload.get("assets") or ():
        if not isinstance(raw, Mapping):
            continue
        name, url = raw.get("name"), raw.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if not is_safe_asset_name(name) or not is_safe_url(url):
            continue  # zasób spoza GitHub albo z nazwą-ścieżką jest pomijany
        size = raw.get("size")
        assets.append(Asset(name, url, size if isinstance(size, int) else 0))

    suffix = ASSET_SUFFIXES.get(platform or "")
    artifact = next(
        (a for a in assets if suffix and a.name.endswith(suffix)),
        None,
    )
    checksums = next((a for a in assets if a.name == CHECKSUMS_ASSET), None)
    signature = next((a for a in assets if a.name == SIGNATURE_ASSET), None)
    return ReleaseInfo(
        version=".".join(str(part) for part in version),
        page_url=safe_page_url(payload.get("html_url")),
        artifact=artifact,
        checksums=checksums,
        signature=signature,
    )


def fetch_latest(client: httpx.Client, platform: str | None) -> ReleaseInfo | None:
    """Jedno zapytanie o najnowsze wydanie.

    Zwraca None, gdy repozytorium nie ma jeszcze żadnego wydania (404).
    Błędy połączenia (``httpx.TransportError``) przechodzą bez zmian — wołający
    odróżnia brak sieci od błędnej odpowiedzi serwera (``UpdateError``).
    """
    response = client.get(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise UpdateError(
            user_message=tr("update.error.server", status=response.status_code),
            retry_hint=tr("update.error.later.hint"),
        )
    try:
        payload = response.json()
    except ValueError as error:
        raise UpdateError(user_message=tr("update.error.unreadable")) from error
    if not isinstance(payload, Mapping):
        raise UpdateError(user_message=tr("update.error.unreadable"))
    return parse_release(payload, platform)
