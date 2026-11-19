"""Ostrzeżenie o wersjach z lukami bezpieczeństwa (``advisory.json``).

Plik leży w osobnym wydaniu GitHub o stałym tagu ``advisory`` (oznaczonym
jako pre-release, więc nigdy nie jest „najnowszym wydaniem”) i publikuje go
workflow „Ostrzeżenie bezpieczeństwa” - także bez nowego wydania programu.
Treść::

    {"sequence": 3, "min_version": "0.10.2",
     "message": {"pl": "…", "en": "…"}}

- ``min_version`` - wersje starsze niż ta mają znaną lukę i program
  ostrzega, żeby je zaktualizować;
- ``message`` - opis dla użytkownika w językach programu (opcjonalny);
- ``sequence`` - numer kolejny, ten sam co w zaufanym komentarzu podpisu
  (``transkryptor advisory <numer>``, ``update/signature.py``).

Pola są trwałym kontraktem ze wszystkimi wydanymi wersjami: nowe pola
wolno dopisywać (starsze wersje je pomijają), ale nie wolno zmieniać
znaczenia ani usuwać istniejących.

Bezpieczeństwo opiera się na podpisie, nie na hoście: plik bez poprawnego
podpisu kluczem wydań jest odrzucany. Ostatnie przyjęte ostrzeżenie zostaje
lokalnie (razem z podpisem, sprawdzanym ponownie przy odczycie) - plik
o niższym numerze jest odrzucany, więc podsunięcie starszego, prawdziwego
ostrzeżenia nie cofnie nowszego, a brak sieci albo usunięty plik nie
wyłączą ostrzeżenia. Błąd pobrania nigdy nie blokuje programu - ostrzeżenie
jest wtedy brane z lokalnej kopii albo go nie ma.

Workflow publikacji składa i sprawdza plik tym samym kodem::

    python -m transkryptor.update.advisory build --sequence N \\
        --min-version X.Y.Z --message-pl … --message-en … --out advisory.json
    python -m transkryptor.update.advisory verify advisory.json \\
        advisory.json.minisig
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from transkryptor.errors import UpdateError
from transkryptor.fileio import write_atomic
from transkryptor.paths import user_data_dir
from transkryptor.update.releases import (
    RELEASES_URL,
    fetch_small,
    is_newer,
    parse_version,
)
from transkryptor.update.signature import (
    SignatureError,
    advisory_comment_for,
    sequence_from_advisory_comment,
    verify,
)

logger = logging.getLogger(__name__)

ADVISORY_TAG = "advisory"
ADVISORY_ASSET = "advisory.json"
ADVISORY_SIGNATURE_ASSET = f"{ADVISORY_ASSET}.minisig"
ADVISORY_URL = f"{RELEASES_URL}/download/{ADVISORY_TAG}/{ADVISORY_ASSET}"
ADVISORY_SIGNATURE_URL = (
    f"{RELEASES_URL}/download/{ADVISORY_TAG}/{ADVISORY_SIGNATURE_ASSET}"
)


class AdvisoryError(ValueError):
    """Treść ostrzeżenia niezgodna z kontraktem (po poprawnym podpisie)."""


@dataclass(frozen=True)
class Advisory:
    sequence: int
    min_version: str
    # Pary (język, tekst) - krotka, żeby obiekt był niezmienny.
    messages: tuple[tuple[str, str], ...] = field(default=())

    def applies_to(self, version: str) -> bool:
        """Czy ``version`` jest starsza niż najniższa bezpieczna wersja."""
        return is_newer(self.min_version, version)

    def message(self, language: str) -> str | None:
        texts = dict(self.messages)
        return texts.get(language) or texts.get("en") or None


def parse_advisory(
    payload: bytes, signature_text: str, trusted_keys: Iterable[str] | None = None
) -> Advisory:
    """Sprawdza podpis i treść; błąd → ``SignatureError`` albo ``AdvisoryError``."""
    sequence = sequence_from_advisory_comment(
        verify(payload, signature_text, trusted_keys)
    )
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdvisoryError("ostrzeżenie: niepoprawny JSON") from error
    if not isinstance(data, dict):
        raise AdvisoryError("ostrzeżenie: oczekiwano obiektu JSON")
    if data.get("sequence") != sequence:
        raise AdvisoryError("ostrzeżenie: numer różny od numeru w podpisie")
    min_version = data.get("min_version")
    if not isinstance(min_version, str) or parse_version(min_version) is None:
        raise AdvisoryError(f"ostrzeżenie: niepoprawna wersja {min_version!r}")
    raw_messages = data.get("message", {})
    if not isinstance(raw_messages, dict):
        raise AdvisoryError("ostrzeżenie: pole message musi być obiektem")
    messages = tuple(
        (language, text.strip())
        for language, text in sorted(raw_messages.items())
        if isinstance(language, str) and isinstance(text, str) and text.strip()
    )
    return Advisory(sequence, min_version, messages)


def build_advisory(sequence: int, min_version: str, messages: dict[str, str]) -> bytes:
    """Treść ``advisory.json`` do podpisania (workflow publikacji)."""
    if sequence < 1:
        raise AdvisoryError("numer ostrzeżenia musi być dodatni")
    if parse_version(min_version) is None:
        raise AdvisoryError(f"niepoprawna wersja {min_version!r}")
    data = {
        "sequence": sequence,
        "min_version": min_version,
        "message": {lang: text for lang, text in messages.items() if text.strip()},
    }
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def default_store_dir() -> Path:
    return user_data_dir() / "advisory"


class AdvisoryStore:
    """Ostatnie przyjęte ostrzeżenie (treść i podpis) w katalogu danych."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory or default_store_dir()

    def load(self, trusted_keys: Iterable[str] | None = None) -> Advisory | None:
        """Kopia sprawdzona ponownie podpisem; brak albo zła kopia → None."""
        try:
            payload = (self.directory / ADVISORY_ASSET).read_bytes()
            signature = (self.directory / ADVISORY_SIGNATURE_ASSET).read_text(
                encoding="utf-8"
            )
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as error:
            logger.warning("Stored advisory unreadable: %s", error)
            return None
        try:
            return parse_advisory(payload, signature, trusted_keys)
        except (SignatureError, AdvisoryError) as error:
            logger.warning("Stored advisory rejected: %s", error)
            return None

    def save(self, payload: bytes, signature: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        # Podpis przed treścią: przerwany zapis zostawia parę, której podpis
        # nie pasuje, a taka kopia jest przy odczycie pomijana.
        write_atomic(
            self.directory / ADVISORY_SIGNATURE_ASSET, signature.encode("utf-8")
        )
        write_atomic(self.directory / ADVISORY_ASSET, payload)


def _fetch_text(client: httpx.Client, url: str) -> bytes | None:
    result = fetch_small(client, url)
    if isinstance(result, httpx.Response):
        if result.status_code == 404:
            return None
        raise UpdateError(f"HTTP {result.status_code} for {url}")
    return result


def fetch_advisory(
    client: httpx.Client, trusted_keys: Iterable[str] | None = None
) -> tuple[Advisory, bytes, str] | None:
    """Ostrzeżenie z wydania ``advisory``; brak pliku → None.

    Błędy połączenia (``httpx.TransportError``), serwera (``UpdateError``),
    podpisu i treści przechodzą do wywołującego.
    """
    payload = _fetch_text(client, ADVISORY_URL)
    if payload is None:
        return None
    signature_bytes = _fetch_text(client, ADVISORY_SIGNATURE_URL)
    if signature_bytes is None:
        raise SignatureError("ostrzeżenie bez podpisu")
    signature = signature_bytes.decode("utf-8", errors="replace")
    return parse_advisory(payload, signature, trusted_keys), payload, signature


def current_advisory(
    client: httpx.Client,
    store: AdvisoryStore,
    trusted_keys: Iterable[str] | None = None,
) -> Advisory | None:
    """Najnowsze znane ostrzeżenie: z sieci, a bez niej z lokalnej kopii.

    Nigdy nie zgłasza błędu - problemy trafiają do dziennika.
    """
    stored = store.load(trusted_keys)
    try:
        fetched = fetch_advisory(client, trusted_keys)
    except (httpx.TransportError, UpdateError, SignatureError, AdvisoryError) as error:
        logger.info("Advisory unavailable: %s", error)
        return stored
    if fetched is None:
        return stored
    advisory, payload, signature = fetched
    if stored is not None and advisory.sequence < stored.sequence:
        logger.warning(
            "Advisory %d older than stored %d - ignored",
            advisory.sequence,
            stored.sequence,
        )
        return stored
    if stored is None or advisory.sequence > stored.sequence:
        try:
            store.save(payload, signature)
        except OSError as error:
            logger.warning("Could not store advisory: %s", error)
    return advisory


def _main_build(args: argparse.Namespace) -> int:
    payload = build_advisory(
        args.sequence, args.min_version, {"pl": args.message_pl, "en": args.message_en}
    )
    args.out.write_bytes(payload)
    # Zaufany komentarz dla ``minisign -t`` - jedyny wiersz na stdout.
    print(advisory_comment_for(args.sequence))
    return 0


def _main_verify(args: argparse.Namespace) -> int:
    advisory = parse_advisory(
        args.advisory.read_bytes(), args.signature.read_text(encoding="utf-8")
    )
    print(
        f"Ostrzeżenie poprawne: numer {advisory.sequence}, "
        f"wersje starsze niż {advisory.min_version}"
    )
    return 0


def _main_next(args: argparse.Namespace) -> int:
    """Następny numer: o jeden większy niż w opublikowanym pliku (albo 1)."""
    current = 0
    if args.advisory.is_file():
        data = json.loads(args.advisory.read_text(encoding="utf-8"))
        current = int(data["sequence"])
    print(current + 1)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.update.advisory",
        description="Ostrzeżenie o wersjach z lukami bezpieczeństwa.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="złóż advisory.json")
    build.add_argument("--sequence", type=int, required=True)
    build.add_argument("--min-version", required=True)
    build.add_argument("--message-pl", default="")
    build.add_argument("--message-en", default="")
    build.add_argument("--out", type=Path, required=True)
    build.set_defaults(handler=_main_build)
    check = commands.add_parser("verify", help="sprawdź podpis i treść")
    check.add_argument("advisory", type=Path)
    check.add_argument("signature", type=Path)
    check.set_defaults(handler=_main_verify)
    following = commands.add_parser("next", help="następny numer ostrzeżenia")
    following.add_argument("advisory", type=Path)
    following.set_defaults(handler=_main_next)
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (SignatureError, AdvisoryError, OSError, ValueError, KeyError) as error:
        print(f"Ostrzeżenie odrzucone: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
