"""Testy pliku projektu ``.transkr`` (faza 08, propozycja 2)."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from transkryptor.document import project
from transkryptor.document.project import (
    SCHEMA_VERSION,
    AsrDraft,
    AsrSegment,
    AudioRef,
    PlayerState,
    ProjectState,
    ReviewEntry,
    audio_ref,
    file_sha256,
    load_project,
    loads,
    migrate,
    resolve_audio,
    save_project,
)
from transkryptor.errors import ProjectError

SAMPLE_MP3 = Path("tests/fixtures/audio/sample.mp3")


def full_state(audio: AudioRef | None = None) -> ProjectState:
    return ProjectState(
        text="uod tego czasu … som\nżółć gęślą jaźń",
        superscript_ranges=((0, 1), (19, 20)),
        author="Łukasz Żółw",
        date="2026-10-09",
        metadata={"signature": "AdK_1954", "place": "Ocieszyn", "custom-1": "x"},
        exported=True,
        audio=audio,
        player=PlayerState(
            position_ms=12_500, loop_a_ms=1000, loop_b_ms=4000, loop_active=True
        ),
        asr=AsrDraft(
            text="od tego czasu … są",
            segments=(AsrSegment(0.0, 2.5, "od tego czasu … są", 0.42),),
        ),
        review=(
            ReviewEntry(
                start=0,
                end=3,
                applied=True,
                code="SUG-LAB-U-INIT",
                suggestion_start=0,
                suggestion_end=2,
                original="od",
                replacement="uod",
                superscript_ranges=((0, 1),),
                confidence=0.5,
                message="Labializacja: …",
                word="od",
                word_start=0,
            ),
        ),
    )


class TestRoundTrip:
    def test_full_state_survives_save_and_load(self, tmp_path) -> None:
        audio = tmp_path / "nagranie.mp3"
        shutil.copy(SAMPLE_MP3, audio)
        state = full_state(audio_ref(audio))
        path = tmp_path / "projekt.transkr"

        save_project(state, path)
        loaded = load_project(path)

        assert loaded.audio is not None
        assert loaded.audio.relative_path == "nagranie.mp3"
        assert loaded.audio.sha256 == state.audio.sha256  # type: ignore[union-attr]
        assert loaded == ProjectState(**{**state.__dict__, "audio": loaded.audio})

    def test_empty_document_without_audio(self, tmp_path) -> None:
        path = tmp_path / "pusty.transkr"
        save_project(ProjectState(), path)
        assert load_project(path) == ProjectState()

    def test_file_is_utf8_json_with_schema_version(self, tmp_path) -> None:
        path = tmp_path / "znaki.transkr"
        save_project(full_state(), path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert "żółć gęślą jaźń" in path.read_text(encoding="utf-8")


class TestAudioResolution:
    def test_relative_path_wins_after_moving_project_folder(self, tmp_path) -> None:
        """Projekt z innego systemu: ścieżka bezwzględna nie istnieje."""
        original = tmp_path / "a"
        (original / "audio").mkdir(parents=True)
        shutil.copy(SAMPLE_MP3, original / "audio" / "n.mp3")
        save_project(
            full_state(audio_ref(original / "audio" / "n.mp3")), original / "p.transkr"
        )
        moved = tmp_path / "b"
        original.rename(moved)

        loaded = load_project(moved / "p.transkr")
        assert loaded.audio is not None
        assert loaded.audio.relative_path == "audio/n.mp3"
        assert (
            resolve_audio(loaded.audio, moved / "p.transkr")
            == moved / "audio" / "n.mp3"
        )

    def test_absolute_path_is_a_fallback(self, tmp_path) -> None:
        ref = AudioRef(str(SAMPLE_MP3.resolve()), "x", relative_path="zgubione.mp3")
        assert resolve_audio(ref, tmp_path / "p.transkr") == SAMPLE_MP3.resolve()

    def test_missing_audio_gives_none(self, tmp_path) -> None:
        ref = AudioRef(str(tmp_path / "brak.mp3"), "x", relative_path="brak.mp3")
        assert resolve_audio(ref, tmp_path / "p.transkr") is None


class TestSchema:
    def test_current_version_needs_no_migration(self) -> None:
        data = {"schema_version": SCHEMA_VERSION, "document": {"text": ""}}
        assert migrate(data) is data

    def test_newer_version_is_rejected_with_hint(self) -> None:
        with pytest.raises(ProjectError) as info:
            migrate({"schema_version": SCHEMA_VERSION + 1})
        assert "nowszej wersji" in info.value.user_message
        assert info.value.retry_hint

    def test_migrations_are_chained(self, monkeypatch) -> None:
        """Mechanizm migracji na sztucznej wersji 2 schematu."""
        monkeypatch.setattr(project, "SCHEMA_VERSION", 2)
        monkeypatch.setitem(
            project._MIGRATIONS,
            1,
            lambda data: {**data, "schema_version": 2, "nowe_pole": []},
        )
        migrated = migrate({"schema_version": 1, "document": {"text": "x"}})
        assert migrated == {
            "schema_version": 2,
            "document": {"text": "x"},
            "nowe_pole": [],
        }

    def test_version_below_one_is_invalid(self) -> None:
        with pytest.raises(ProjectError):
            migrate({"schema_version": 0})

    @pytest.mark.parametrize(
        "raw",
        [
            "nie json",
            "[]",
            '{"schema_version": "1"}',
            '{"schema_version": 1}',
            '{"schema_version": 1, "document": {"text": 5}}',
            '{"schema_version": 1, "document": {"text": "ab",'
            ' "superscript_ranges": [[1, 5]]}}',
            '{"schema_version": 1, "document": {"text": "ab"},'
            ' "review": [{"start": 0, "end": 9}]}',
        ],
    )
    def test_invalid_content_raises_project_error(self, raw) -> None:
        with pytest.raises(ProjectError) as info:
            loads(raw)
        assert "nie jest poprawnym projektem" in info.value.user_message

    def test_load_error_names_the_file(self, tmp_path) -> None:
        path = tmp_path / "zły.transkr"
        path.write_bytes(b"\xff\xfe")
        with pytest.raises(ProjectError) as info:
            load_project(path)
        assert "zły.transkr" in info.value.user_message
        with pytest.raises(ProjectError):
            load_project(tmp_path / "brak.transkr")


class TestAtomicWrite:
    def test_interrupted_save_keeps_previous_file(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "projekt.transkr"
        save_project(ProjectState(text="poprzednia wersja"), path)
        before = path.read_bytes()

        def broken_replace(src, dst):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "replace", broken_replace)
        with pytest.raises(ProjectError) as info:
            save_project(ProjectState(text="nowa wersja"), path)
        assert info.value.retry_hint

        assert path.read_bytes() == before
        assert [p.name for p in tmp_path.iterdir()] == ["projekt.transkr"]

    def test_unwritable_directory_raises_project_error(self, tmp_path) -> None:
        with pytest.raises(ProjectError):
            save_project(ProjectState(), tmp_path / "brak" / "p.transkr")


posix_only = pytest.mark.skipif(os.name != "posix", reason="prawa POSIX")


@posix_only
class TestFilePermissions:
    """BUG-04: zapis nie zmienia praw pliku projektu na ``0600``."""

    @pytest.fixture
    def umask_022(self):
        previous = os.umask(0o022)
        yield
        os.umask(previous)

    def test_new_project_gets_default_permissions(self, tmp_path, umask_022) -> None:
        path = tmp_path / "p.transkr"
        save_project(ProjectState(text="a"), path)
        assert path.stat().st_mode & 0o777 == 0o644

    def test_existing_permissions_are_kept(self, tmp_path, umask_022) -> None:
        path = tmp_path / "p.transkr"
        save_project(ProjectState(text="a"), path)
        path.chmod(0o664)
        save_project(ProjectState(text="b"), path)
        assert path.stat().st_mode & 0o777 == 0o664

    def test_explicit_mode_wins(self, tmp_path, umask_022) -> None:
        path = tmp_path / "kopia.transkr"
        project.write_atomic(path, b"{}", mode=0o600)
        assert path.stat().st_mode & 0o777 == 0o600


def test_file_sha256_can_be_interrupted(tmp_path) -> None:
    path = tmp_path / "duzy.bin"
    path.write_bytes(b"x" * (3 << 20))
    with pytest.raises(InterruptedError):
        file_sha256(path, should_cancel=lambda: True)
    assert file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()
