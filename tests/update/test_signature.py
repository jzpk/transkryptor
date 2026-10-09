"""Testy weryfikacji podpisu minisign sum kontrolnych wydania."""

from __future__ import annotations

import base64

import pytest

from transkryptor.update import keys
from transkryptor.update.signature import (
    SignatureError,
    main,
    trusted_comment_for,
    verify,
    verify_release_checksums,
)

SUMS = b"abc  Transkryptor-1.0.0-x86_64.AppImage\n"
COMMENT = trusted_comment_for("1.0.0")


def test_valid_signature_returns_the_trusted_comment(release_key) -> None:
    signature = release_key.sign(SUMS, COMMENT)
    assert verify(SUMS, signature) == COMMENT
    verify_release_checksums(SUMS, signature, "1.0.0")


def test_changed_content_is_rejected(release_key) -> None:
    signature = release_key.sign(SUMS, COMMENT)
    with pytest.raises(SignatureError):
        verify(SUMS + b"x", signature)


def test_changed_trusted_comment_is_rejected(release_key) -> None:
    signature = release_key.sign(SUMS, COMMENT)
    forged = signature.replace(COMMENT, trusted_comment_for("9.9.9"))
    with pytest.raises(SignatureError):
        verify(SUMS, forged)


def test_signature_for_another_version_is_rejected(release_key) -> None:
    signature = release_key.sign(SUMS, trusted_comment_for("0.9.0"))
    with pytest.raises(SignatureError):
        verify_release_checksums(SUMS, signature, "1.0.0")


def test_unknown_key_is_rejected(foreign_key) -> None:
    with pytest.raises(SignatureError):
        verify(SUMS, foreign_key.sign(SUMS, COMMENT))


def test_key_id_of_a_trusted_key_with_foreign_signature_is_rejected(
    release_key, foreign_key
) -> None:
    """Identyfikator klucza nie wystarczy — liczy się sam podpis."""
    lines = foreign_key.sign(SUMS, COMMENT).splitlines()
    raw = bytearray(base64.b64decode(lines[1]))
    raw[2:10] = release_key.key_id
    lines[1] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(SignatureError):
        verify(SUMS, "\n".join(lines))


def test_legacy_algorithm_without_prehash_is_rejected(release_key) -> None:
    with pytest.raises(SignatureError):
        verify(SUMS, release_key.sign(SUMS, COMMENT, algorithm=b"Ed"))


@pytest.mark.parametrize(
    "text",
    ["", "jedna linia", "a\n!!!\ntrusted comment: x\n!!!\n", "a\nAAAA\nb\nAAAA\n"],
)
def test_malformed_signature_file_is_rejected(text) -> None:
    with pytest.raises(SignatureError):
        verify(SUMS, text)


def test_without_trusted_keys_nothing_verifies(release_key) -> None:
    with pytest.raises(SignatureError):
        verify(SUMS, release_key.sign(SUMS, COMMENT), trusted_keys=())


def test_command_line_check_used_by_the_release_workflow(
    release_key, tmp_path, capsys
) -> None:
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_bytes(SUMS)
    signature = tmp_path / "SHA256SUMS.txt.minisig"
    signature.write_text(release_key.sign(SUMS, COMMENT), encoding="utf-8")
    assert main([str(sums), str(signature), "--version", "1.0.0"]) == 0
    assert main([str(sums), str(signature), "--version", "1.0.1"]) == 1
    assert "Podpis odrzucony" in capsys.readouterr().err


def test_release_gate_requires_a_valid_embedded_key(release_key) -> None:
    assert keys.key_problems((release_key.public,)) == []
    assert keys.key_problems(()) != []
    assert keys.key_problems(("RWQnie-klucz",)) != []
