"""Weryfikacja podpisu minisign pliku ``SHA256SUMS.txt``.

Sumy kontrolne z wydania chronią tylko przed uszkodzeniem transmisji: kto
podmieni artefakt w wydaniu, podmieni też sumy. Dlatego sumy są podpisywane
kluczem, którego część publiczna jest wbudowana w aplikację
(``update/keys.py``), a prywatna jest tylko w sekrecie workflow wydania.

Obsługiwany jest format minisign z prehashem (algorytm ``ED``, domyślny od
minisign 0.11): podpis Ed25519 obejmuje BLAKE2b-512 treści, a podpis globalny
— podpis i zaufany komentarz. Zaufany komentarz ma postać
``transkryptor <wersja> SHA256SUMS.txt``; wersja musi zgadzać się z wydaniem,
inaczej podpisane sumy starszego wydania dałoby się podstawić pod nowy tag.

Workflow wydania sprawdza podpis tym samym kodem::

    python -m transkryptor.update.signature SHA256SUMS.txt \\
        SHA256SUMS.txt.minisig --version X.Y.Z
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from transkryptor.update import keys

KEY_ALGORITHM = b"Ed"
PREHASHED_ALGORITHM = b"ED"
TRUSTED_COMMENT_PREFIX = "trusted comment: "
COMMENT_PRODUCT = "transkryptor"
COMMENT_FILE = "SHA256SUMS.txt"


class SignatureError(ValueError):
    """Podpis brakujący, uszkodzony albo niepasujący do zaufanego klucza."""


@dataclass(frozen=True)
class _Signature:
    key_id: bytes
    signature: bytes
    trusted_comment: str
    global_signature: bytes


def _b64(text: str, size: int, what: str) -> bytes:
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as error:
        raise SignatureError(f"{what}: niepoprawne base64") from error
    if len(raw) != size:
        raise SignatureError(f"{what}: zła długość ({len(raw)} B)")
    return raw


def parse_public_key(text: str) -> tuple[bytes, Ed25519PublicKey]:
    """Klucz publiczny minisign (base64) → (identyfikator, klucz)."""
    raw = _b64(text, 42, "klucz publiczny")
    if raw[:2] != KEY_ALGORITHM:
        raise SignatureError("klucz publiczny: nieobsługiwany algorytm")
    return raw[2:10], Ed25519PublicKey.from_public_bytes(raw[10:])


def parse_signature(text: str) -> _Signature:
    """Plik ``.minisig``: komentarz, podpis, zaufany komentarz, podpis globalny."""
    lines = text.splitlines()
    if len(lines) < 4 or not lines[2].startswith(TRUSTED_COMMENT_PREFIX):
        raise SignatureError("podpis: niepoprawny format pliku")
    raw = _b64(lines[1], 74, "podpis")
    if raw[:2] != PREHASHED_ALGORITHM:
        raise SignatureError("podpis: wymagany algorytm ED (minisign z prehashem)")
    return _Signature(
        key_id=raw[2:10],
        signature=raw[10:],
        trusted_comment=lines[2][len(TRUSTED_COMMENT_PREFIX) :],
        global_signature=_b64(lines[3], 64, "podpis globalny"),
    )


def verify(
    message: bytes, signature_text: str, trusted_keys: Iterable[str] | None = None
) -> str:
    """Sprawdza podpis treści i zwraca zaufany komentarz.

    ``trusted_keys=None`` oznacza klucze wbudowane (``keys.TRUSTED_KEYS``),
    odczytane przy wywołaniu.
    """
    signature = parse_signature(signature_text)
    candidates = keys.TRUSTED_KEYS if trusted_keys is None else tuple(trusted_keys)
    if not candidates:
        raise SignatureError("brak zaufanego klucza publicznego")
    public_key = None
    for candidate in candidates:
        key_id, key = parse_public_key(candidate)
        if key_id == signature.key_id:
            public_key = key
            break
    if public_key is None:
        raise SignatureError("podpis złożony nieznanym kluczem")
    digest = hashlib.blake2b(message, digest_size=64).digest()
    try:
        public_key.verify(signature.signature, digest)
        public_key.verify(
            signature.global_signature,
            signature.signature + signature.trusted_comment.encode("utf-8"),
        )
    except InvalidSignature as error:
        raise SignatureError("podpis nie pasuje do treści") from error
    return signature.trusted_comment


def trusted_comment_for(version: str) -> str:
    """Zaufany komentarz, którym workflow wydania podpisuje sumy wersji."""
    return f"{COMMENT_PRODUCT} {version} {COMMENT_FILE}"


def verify_release_checksums(
    checksums: bytes,
    signature_text: str,
    version: str,
    trusted_keys: Iterable[str] | None = None,
) -> None:
    """Podpis sum kontrolnych wydania ``version``; błąd → ``SignatureError``."""
    comment = verify(checksums, signature_text, trusted_keys)
    if comment != trusted_comment_for(version):
        raise SignatureError(
            f"podpis dotyczy innego wydania ({comment!r}, oczekiwano {version})"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m transkryptor.update.signature",
        description="Podpis sum kontrolnych wydania (minisign).",
    )
    parser.add_argument("checksums", type=Path)
    parser.add_argument("signature", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)

    try:
        verify_release_checksums(
            args.checksums.read_bytes(),
            args.signature.read_text(encoding="utf-8"),
            args.version,
        )
    except (SignatureError, OSError) as error:
        print(f"Podpis odrzucony: {error}", file=sys.stderr)
        return 1
    print(f"Podpis poprawny: {args.checksums.name} (wersja {args.version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
