"""Seria nagrań: rozpakowanie ZIP, kolejność nagrań i projekty obok nich."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from transkryptor.corpus.series import (
    extract_series,
    first_unfinished,
    project_for,
    series_position,
    series_recordings,
)
from transkryptor.errors import ProjectError


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _touch(folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / name for name in names]
    for path in paths:
        path.write_bytes(b"audio")
    return paths


class TestOrder:
    def test_recordings_sorted_naturally_without_other_files(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, "w10.mp3", "w2.wav", "w1.MP3", "notes.txt", ".hidden.mp3")
        (tmp_path / "sub").mkdir()
        _touch(tmp_path / "sub", "w0.mp3")
        names = [path.name for path in series_recordings(tmp_path)]
        assert names == ["w1.MP3", "w2.wav", "w10.mp3"]

    def test_position_and_next(self, tmp_path: Path) -> None:
        first, second, third = _touch(tmp_path, "a1.mp3", "a2.mp3", "a3.mp3")
        project_for(first).write_text("{}", encoding="utf-8")
        position = series_position(second)
        assert position is not None
        assert (position.number, position.total, position.done) == (2, 3, 1)
        assert position.next_recording == third
        last = series_position(third)
        assert last is not None and last.next_recording is None

    def test_single_recording_is_not_a_series(self, tmp_path: Path) -> None:
        (only,) = _touch(tmp_path, "a.mp3")
        assert series_position(only) is None

    def test_first_unfinished(self, tmp_path: Path) -> None:
        recordings = _touch(tmp_path, "a1.mp3", "a2.mp3")
        project_for(recordings[0]).write_text("{}", encoding="utf-8")
        assert first_unfinished(recordings) == recordings[1]
        project_for(recordings[1]).write_text("{}", encoding="utf-8")
        assert first_unfinished(recordings) == recordings[0]

    def test_project_name_keeps_suffix_for_same_stem(self, tmp_path: Path) -> None:
        mp3, wav, other = _touch(tmp_path, "a.mp3", "a.wav", "b.mp3")
        recordings = [mp3, wav, other]
        assert project_for(mp3, recordings).name == "a.mp3.transkr"
        assert project_for(wav, recordings).name == "a.wav.transkr"
        assert project_for(other, recordings).name == "b.transkr"


class TestExtract:
    def test_extracts_only_recordings_flat(self, tmp_path: Path) -> None:
        archive = _zip(
            tmp_path / "seria.zip",
            {
                "seria/w2.mp3": b"two",
                "seria/w10.mp3": b"ten",
                "seria/inne/w1.wav": b"one",
                "seria/opis.txt": b"x",
                "__MACOSX/seria/._w2.mp3": b"junk",
                "seria/.DS_Store": b"junk",
            },
        )
        folder = tmp_path / "out" / "seria"
        result = extract_series(archive, folder)
        assert [p.name for p in result.recordings] == ["w1.wav", "w2.mp3", "w10.mp3"]
        assert (folder / "w10.mp3").read_bytes() == b"ten"
        assert result.skipped == ("opis.txt",)
        assert sorted(p.name for p in folder.iterdir()) == [
            "w1.wav",
            "w10.mp3",
            "w2.mp3",
        ]

    def test_same_names_get_numbers(self, tmp_path: Path) -> None:
        archive = _zip(tmp_path / "s.zip", {"a/x.mp3": b"1", "b/x.mp3": b"22"})
        result = extract_series(archive, tmp_path / "s")
        assert sorted(p.name for p in result.recordings) == ["x (2).mp3", "x.mp3"]

    def test_reimport_keeps_existing_recordings_and_projects(
        self, tmp_path: Path
    ) -> None:
        archive = _zip(tmp_path / "s.zip", {"a.mp3": b"aaa", "b.mp3": b"bbb"})
        folder = tmp_path / "s"
        extract_series(archive, folder)
        project_for(folder / "a.mp3").write_text("{}", encoding="utf-8")
        again = extract_series(archive, folder)
        assert again.extracted == ()
        assert [p.name for p in again.recordings] == ["a.mp3", "b.mp3"]
        assert project_for(folder / "a.mp3").is_file()

    def test_different_file_with_same_name_is_not_overwritten(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "s"
        _touch(folder, "a.mp3")  # 5 bajtów - inne nagranie
        archive = _zip(tmp_path / "s.zip", {"a.mp3": b"xyz"})
        result = extract_series(archive, folder)
        assert (folder / "a.mp3").read_bytes() == b"audio"
        assert [p.name for p in result.extracted] == ["a (2).mp3"]

    def test_unsafe_names_stay_inside_folder(self, tmp_path: Path) -> None:
        archive = _zip(tmp_path / "s.zip", {"../../evil.mp3": b"e", "/abs.mp3": b"a"})
        folder = tmp_path / "out"
        result = extract_series(archive, folder)
        assert all(path.parent == folder for path in result.recordings)
        assert not (tmp_path / "evil.mp3").exists()

    def test_archive_without_recordings(self, tmp_path: Path) -> None:
        archive = _zip(tmp_path / "s.zip", {"a.txt": b"x"})
        with pytest.raises(ProjectError):
            extract_series(archive, tmp_path / "s")

    def test_broken_archive(self, tmp_path: Path) -> None:
        archive = tmp_path / "s.zip"
        archive.write_bytes(b"not a zip")
        with pytest.raises(ProjectError):
            extract_series(archive, tmp_path / "s")
