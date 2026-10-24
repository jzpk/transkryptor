"""Testy pliku projektu ``.transkr`` (faza 08, propozycja 2)."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from transkryptor.document import project
from transkryptor.document.anchors import MANUAL, SEGMENT, WORD, Anchor
from transkryptor.document.project import (
    SCHEMA_VERSION,
    AsrContext,
    AsrDraft,
    AsrSegment,
    AudioRef,
    IgnoredWarning,
    PlayerState,
    ProjectState,
    ReviewEntry,
    audio_ref,
    dumps,
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
            model="large-v3",
        ),
        asr_context=AsrContext(
            prompt="Wywiad w Ocieszynie", vocabulary=("Ocieszyn", "Oborniki")
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
        """Mechanizm migracji na sztucznej kolejnej wersji schematu."""
        next_version = SCHEMA_VERSION + 1
        monkeypatch.setattr(project, "SCHEMA_VERSION", next_version)
        monkeypatch.setitem(
            project._MIGRATIONS,
            SCHEMA_VERSION,
            lambda data: {**data, "schema_version": next_version, "nowe_pole": []},
        )
        migrated = migrate({"schema_version": 1, "document": {"text": "x"}})
        assert migrated == {
            "schema_version": next_version,
            "document": {
                "text": "x",
                "speakers": [
                    {"key": "B", "label": "", "role": "researcher"},
                    {"key": "I", "label": "", "role": "informant"},
                ],
                "paragraph_speakers": [],
            },
            "asr_context": {"prompt": "", "vocabulary": []},
            "ignored_warnings": [],
            "anchors": [],
            "comments": [],
            "nowe_pole": [],
        }

    def test_version_1_project_gets_empty_asr_context(self) -> None:
        """Projekt z wydania 0.3.0 otwiera się z pustym kontekstem ASR."""
        state = loads(
            json.dumps(
                {
                    "schema_version": 1,
                    "document": {"text": "tekst"},
                    "asr": {"text": "tekst", "segments": []},
                }
            )
        )
        assert state.text == "tekst"
        assert state.asr_context == AsrContext()
        assert state.asr is not None and state.asr.model is None

    def test_version_2_project_has_no_ignored_warnings(self) -> None:
        """Projekt z wydania 0.4.0 otwiera się bez zignorowanych ostrzeżeń."""
        state = loads(json.dumps({"schema_version": 2, "document": {"text": "tekst"}}))
        assert state.ignored_warnings == ()

    def test_ignored_warnings_round_trip(self) -> None:
        state = ProjectState(
            text="a  b",
            ignored_warnings=(IgnoredWarning("VAL-07", 1, 3, "  "),),
        )
        assert loads(dumps(state)).ignored_warnings == state.ignored_warnings

    def test_ignored_warning_outside_text_is_invalid(self) -> None:
        raw = json.dumps(
            {
                "schema_version": 3,
                "document": {"text": "ab"},
                "ignored_warnings": [{"code": "VAL-07", "start": 0, "end": 9}],
            }
        )
        with pytest.raises(ProjectError):
            loads(raw)

    def test_version_3_project_has_no_anchors(self) -> None:
        """Projekt sprzed fazy 11 otwiera się bez kotwic czasowych."""
        state = loads(json.dumps({"schema_version": 3, "document": {"text": "ab"}}))
        assert state.anchors == ()

    def test_asr_segment_speakers_round_trip(self) -> None:
        """Podział na mówców: numer mówcy segmentu ASR przetrwa zapis."""
        state = ProjectState(
            asr=AsrDraft(
                text="a b",
                segments=(
                    AsrSegment(0.0, 1.0, " a", 0.9, speaker=0),
                    AsrSegment(1.0, 2.0, " b", 0.9, speaker=1),
                    AsrSegment(2.0, 3.0, " c", 0.9),
                ),
            )
        )
        data = json.loads(dumps(state))
        assert "speaker" not in data["asr"]["segments"][2]
        assert loads(dumps(state)).asr == state.asr

    def test_anchors_round_trip(self) -> None:
        state = ProjectState(
            text="ala ma kota",
            anchors=(
                Anchor(0, 11, 1000, 4000, SEGMENT),
                Anchor(4, 6, 2000, 2500, WORD, probability=0.31),
                Anchor(7, 11, 2500, 3000, WORD, probability=0.2, edited=True),
                Anchor(4, 4, 1800, 1800, MANUAL),
            ),
        )
        assert loads(dumps(state)).anchors == state.anchors

    @pytest.mark.parametrize(
        "anchor",
        [
            {"start": 0, "end": 9, "start_ms": 0, "end_ms": 1, "source": "segment"},
            {"start": 0, "end": 1, "start_ms": 5, "end_ms": 1, "source": "segment"},
            {"start": 0, "end": 1, "start_ms": 0, "end_ms": 1, "source": "inne"},
            {"start": 0, "end": 1, "start_ms": 0, "end_ms": 0, "source": "manual"},
            {"start": 1, "end": 1, "start_ms": 0, "end_ms": 1, "source": "word"},
        ],
    )
    def test_invalid_anchor_is_rejected(self, anchor) -> None:
        raw = json.dumps(
            {"schema_version": 4, "document": {"text": "ab"}, "anchors": [anchor]}
        )
        with pytest.raises(ProjectError):
            loads(raw)

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
