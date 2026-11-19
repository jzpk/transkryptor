"""Testy podpisanego ostrzeżenia o wersjach z lukami bezpieczeństwa."""

from __future__ import annotations

import pytest

from transkryptor.update.advisory import (
    AdvisoryError,
    AdvisoryStore,
    build_advisory,
    current_advisory,
    main,
    parse_advisory,
)
from transkryptor.update.signature import (
    SignatureError,
    advisory_comment_for,
    trusted_comment_for,
)

MESSAGES = {"pl": "Luka w imporcie DOCX.", "en": "DOCX import vulnerability."}


@pytest.fixture
def store(tmp_path) -> AdvisoryStore:
    return AdvisoryStore(tmp_path / "advisory")


def signed(release_key, sequence=1, min_version="0.10.1", messages=None):
    payload = build_advisory(sequence, min_version, messages or MESSAGES)
    return payload, release_key.sign(payload, advisory_comment_for(sequence))


def test_signed_advisory_is_parsed(release_key) -> None:
    advisory = parse_advisory(*signed(release_key, 3))
    assert advisory.sequence == 3
    assert advisory.min_version == "0.10.1"
    assert advisory.message("pl") == MESSAGES["pl"]
    assert advisory.message("de") == MESSAGES["en"]


def test_advisory_applies_only_to_older_versions(release_key) -> None:
    advisory = parse_advisory(*signed(release_key, min_version="0.10.1"))
    assert advisory.applies_to("0.10.0")
    assert not advisory.applies_to("0.10.1")
    assert not advisory.applies_to("0.11.0")


def test_foreign_key_is_rejected(foreign_key) -> None:
    with pytest.raises(SignatureError):
        parse_advisory(*signed(foreign_key))


def test_release_signature_is_not_an_advisory(release_key) -> None:
    payload = build_advisory(1, "0.10.1", MESSAGES)
    signature = release_key.sign(payload, trusted_comment_for("0.10.1"))
    with pytest.raises(SignatureError):
        parse_advisory(payload, signature)


def test_sequence_must_match_the_signature(release_key) -> None:
    payload = build_advisory(2, "0.10.1", MESSAGES)
    with pytest.raises(AdvisoryError):
        parse_advisory(payload, release_key.sign(payload, advisory_comment_for(5)))


@pytest.mark.parametrize(
    "payload",
    [
        b"nie json",
        b"[]",
        b'{"sequence": 1, "min_version": "abc"}',
        b'{"sequence": 1, "min_version": "1.0.0", "message": "tekst"}',
    ],
)
def test_malformed_content_is_rejected(release_key, payload) -> None:
    with pytest.raises(AdvisoryError):
        parse_advisory(payload, release_key.sign(payload, advisory_comment_for(1)))


def test_unknown_fields_are_ignored(release_key) -> None:
    """Nowe pola w przyszłych ostrzeżeniach nie psują starszych wersji."""
    payload = b'{"sequence": 1, "min_version": "1.0.0", "severity": "high"}'
    advisory = parse_advisory(
        payload, release_key.sign(payload, advisory_comment_for(1))
    )
    assert advisory.min_version == "1.0.0"
    assert advisory.message("pl") is None


def test_no_advisory_published(github, store) -> None:
    with github.client() as client:
        assert current_advisory(client, store) is None


def test_fetched_advisory_is_stored(github, store) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        advisory = current_advisory(client, store)
    assert advisory is not None and advisory.sequence == 1
    assert store.load() == advisory


def test_stored_advisory_is_used_offline(github, store) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    github.offline = True
    with github.client() as client:
        advisory = current_advisory(client, store)
    assert advisory is not None and advisory.min_version == "0.10.1"


def test_removed_file_keeps_the_stored_advisory(github, store) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    github.advisory_files = {}
    with github.client() as client:
        assert current_advisory(client, store) == store.load()


def test_older_advisory_does_not_roll_back(github, store) -> None:
    github.publish_advisory(2, "0.10.2", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        advisory = current_advisory(client, store)
    assert advisory is not None and advisory.sequence == 2
    assert advisory.min_version == "0.10.2"


def test_newer_advisory_replaces_the_stored_one(github, store) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    github.publish_advisory(2, "0.10.3", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    stored = store.load()
    assert stored is not None and stored.min_version == "0.10.3"


def test_forged_advisory_is_ignored(github, store, foreign_key) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    github.publish_advisory(9, "99.0.0", MESSAGES, key=foreign_key)
    with github.client() as client:
        advisory = current_advisory(client, store)
    assert advisory is not None and advisory.sequence == 1


def test_tampered_stored_copy_is_ignored(github, store) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    with github.client() as client:
        current_advisory(client, store)
    path = store.directory / "advisory.json"
    path.write_bytes(path.read_bytes().replace(b"0.10.1", b"99.0.0"))
    assert store.load() is None


def test_advisory_without_signature_is_ignored(github, store) -> None:
    github.publish_advisory(1, "0.10.1", MESSAGES)
    del github.advisory_files["advisory.json.minisig"]
    with github.client() as client:
        assert current_advisory(client, store) is None


def test_cli_builds_and_verifies(release_key, tmp_path, capsys) -> None:
    out = tmp_path / "advisory.json"
    assert main(["next", str(out)]) == 0
    assert capsys.readouterr().out.strip() == "1"
    args = ["build", "--sequence", "1", "--min-version", "0.10.1"]
    args += ["--message-pl", "Luka.", "--out", str(out)]
    assert main(args) == 0
    comment = capsys.readouterr().out.strip()
    assert comment == advisory_comment_for(1)
    signature = tmp_path / "advisory.json.minisig"
    signature.write_text(release_key.sign(out.read_bytes(), comment), encoding="utf-8")
    assert main(["verify", str(out), str(signature)]) == 0
    assert main(["next", str(out)]) == 0
    assert capsys.readouterr().out.strip().endswith("2")


def test_cli_rejects_foreign_signature(foreign_key, tmp_path) -> None:
    out = tmp_path / "advisory.json"
    out.write_bytes(build_advisory(1, "0.10.1", MESSAGES))
    signature = tmp_path / "advisory.json.minisig"
    signature.write_text(
        foreign_key.sign(out.read_bytes(), advisory_comment_for(1)), encoding="utf-8"
    )
    assert main(["verify", str(out), str(signature)]) == 1
