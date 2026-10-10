"""Klucze publiczne, którymi podpisywane są wydania (minisign, Ed25519).

Każdy wpis to druga linia pliku ``.pub`` z ``minisign -G`` (base64, zaczyna
się od ``RW``). Aktualizacja jest instalowana tylko wtedy, gdy podpis
``SHA256SUMS.txt`` pasuje do jednego z tych kluczy. Krotka pozwala na
rotację: nowy klucz dopisuje się w wydaniu podpisanym jeszcze starym, a stary
usuwa dopiero w kolejnym.

Pusta krotka oznacza, że aplikacja nie zaufa żadnej aktualizacji — workflow
wydania przerywa publikację, dopóki klucz nie zostanie tu wpisany
(``python -m transkryptor.update.keys``). Moduł nie ma zależności, więc
sprawdza go także gołe ``python3`` w CI.
"""

from __future__ import annotations

import base64
import binascii
import sys

TRUSTED_KEYS: tuple[str, ...] = ("RWSZ29IK8ei9r8LjO/svHHZOZHkJe06wAcWxmYusdTiFl8Kl0Tm3N8EV",)


def key_problems(keys: tuple[str, ...] = TRUSTED_KEYS) -> list[str]:
    """Problemy z listą kluczy (pusta lista = gotowe do wydania)."""
    if not keys:
        return ["brak klucza publicznego w src/transkryptor/update/keys.py"]
    problems = []
    for key in keys:
        try:
            raw = base64.b64decode(key, validate=True)
        except (binascii.Error, ValueError):
            raw = b""
        if len(raw) != 42 or raw[:2] != b"Ed":
            problems.append(f"to nie jest klucz publiczny minisign: {key!r}")
    return problems


if __name__ == "__main__":
    found = key_problems()
    for problem in found:
        print(f"::error::{problem}", file=sys.stderr)
    if not found:
        print(f"Zaufane klucze wydań: {len(TRUSTED_KEYS)}")
    raise SystemExit(1 if found else 0)
