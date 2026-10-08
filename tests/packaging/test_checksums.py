"""Testy sum kontrolnych publikowanych razem z artefaktami."""

import hashlib

from transkryptor.packaging import checksums


def test_digest_matches_reference_implementation(tmp_path) -> None:
    artifact = tmp_path / "artefakt.bin"
    artifact.write_bytes(b"transkryptor" * 1000)
    assert (
        checksums.sha256_file(artifact)
        == hashlib.sha256(artifact.read_bytes()).hexdigest()
    )


def test_file_format_is_readable_by_sha256sum(tmp_path) -> None:
    artifact = tmp_path / "Transkryptor.AppImage"
    artifact.write_bytes(b"dane")
    target = checksums.write_checksums([artifact], tmp_path)
    line = target.read_text(encoding="utf-8").splitlines()[0]
    digest, separator, name = line.partition("  ")
    assert separator == "  "
    assert len(digest) == 64
    assert name == artifact.name


def test_entries_are_sorted_by_name(tmp_path) -> None:
    for name in ("b.bin", "a.bin", "c.bin"):
        (tmp_path / name).write_bytes(name.encode())
    entries = checksums.checksums_for(sorted(tmp_path.iterdir(), reverse=True))
    assert [entry.name for entry in entries] == ["a.bin", "b.bin", "c.bin"]


def test_verification_accepts_an_untouched_release(tmp_path) -> None:
    artifact = tmp_path / "artefakt.bin"
    artifact.write_bytes(b"dane wydania")
    target = checksums.write_checksums([artifact], tmp_path)
    assert checksums.verify_checksums(target) == []


def test_verification_detects_modified_artifact(tmp_path) -> None:
    artifact = tmp_path / "artefakt.bin"
    artifact.write_bytes(b"dane wydania")
    target = checksums.write_checksums([artifact], tmp_path)
    artifact.write_bytes(b"podmienione dane")
    problems = checksums.verify_checksums(target)
    assert problems == ["niezgodna suma kontrolna: artefakt.bin"]


def test_verification_detects_missing_artifact(tmp_path) -> None:
    artifact = tmp_path / "artefakt.bin"
    artifact.write_bytes(b"dane")
    target = checksums.write_checksums([artifact], tmp_path)
    artifact.unlink()
    assert checksums.verify_checksums(target) == ["brak pliku: artefakt.bin"]


def test_size_is_recorded_for_release_notes(tmp_path) -> None:
    artifact = tmp_path / "artefakt.bin"
    artifact.write_bytes(b"x" * 4096)
    entry = checksums.checksums_for([artifact])[0]
    assert entry.size_bytes == 4096
