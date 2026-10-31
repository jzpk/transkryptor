"""Migawki projektu: zapis, lista, odczyt, przycinanie i przeniesienie."""

import json
import os
from datetime import datetime, timedelta

import pytest

from transkryptor.document.project import ProjectState
from transkryptor.document.snapshots import (
    MAX_AUTOMATIC,
    MAX_AUTOMATIC_AGE,
    SnapshotStore,
    project_key,
    session_key,
)
from transkryptor.errors import ProjectError

NOW = datetime(2026, 10, 31, 12, 0, 0)


@pytest.fixture
def store(tmp_path) -> SnapshotStore:
    return SnapshotStore(tmp_path / "migawki")


def test_save_list_and_load(store) -> None:
    state = ProjectState(text="raz dwa trzy", author="Ala")
    saved = store.save(state, "przed recenzją", now=NOW)
    assert saved.label == "przed recenzją"
    assert saved.word_count == 3
    assert not saved.automatic
    assert store.list() == [saved]
    assert store.load(saved) == state


def test_newest_first_and_same_second_does_not_overwrite(store) -> None:
    first = store.save(ProjectState(text="a"), "pierwsza", now=NOW)
    second = store.save(ProjectState(text="a b"), "druga", now=NOW)
    third = store.save(ProjectState(text="a b c"), "trzecia", now=NOW + timedelta(1))
    assert first.path != second.path
    assert [s.label for s in store.list()][0] == third.label
    assert {s.label for s in store.list()} == {"pierwsza", "druga", "trzecia"}


def test_automatic_snapshots_are_pruned_manual_stay(store) -> None:
    old = NOW - MAX_AUTOMATIC_AGE - timedelta(days=1)
    store.save(ProjectState(text="stara"), "stara", automatic=True, now=old)
    store.save(ProjectState(text="ręczna"), "ręczna", now=old)
    for minute in range(MAX_AUTOMATIC + 3):
        store.save(
            ProjectState(text="x"),
            f"auto {minute}",
            automatic=True,
            now=NOW + timedelta(minutes=minute),
        )
    snapshots = store.list()
    automatic = [s for s in snapshots if s.automatic]
    assert len(automatic) == MAX_AUTOMATIC
    assert automatic[0].label == f"auto {MAX_AUTOMATIC + 2}"
    assert [s.label for s in snapshots if not s.automatic] == ["ręczna"]


def test_unreadable_files_are_skipped(store) -> None:
    store.save(ProjectState(text="dobra"), "dobra", now=NOW)
    (store.directory / "zepsuta.json").write_text("{", encoding="utf-8")
    (store.directory / "obca.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert [s.label for s in store.list()] == ["dobra"]


def test_damaged_snapshot_raises_project_error(store) -> None:
    saved = store.save(ProjectState(text="a"), "a", now=NOW)
    saved.path.write_text("{", encoding="utf-8")
    with pytest.raises(ProjectError):
        store.load(saved)


def test_delete(store) -> None:
    saved = store.save(ProjectState(text="a"), "a", now=NOW)
    store.delete(saved)
    store.delete(saved)  # drugi raz bez błędu
    assert store.list() == []


@pytest.mark.skipif(os.name != "posix", reason="prawa plików POSIX")
def test_snapshot_is_private(store) -> None:
    saved = store.save(ProjectState(text="a"), "a", now=NOW)
    assert saved.path.stat().st_mode & 0o777 == 0o600


def test_move_to_project_directory(tmp_path, store) -> None:
    store.save(ProjectState(text="a"), "sesja", now=NOW)
    moved = store.move_to(tmp_path / "projekt")
    assert [s.label for s in moved.list()] == ["sesja"]
    assert not store.directory.exists()


def test_keys(tmp_path) -> None:
    assert project_key(tmp_path / "a.transkr") != project_key(tmp_path / "b.transkr")
    assert project_key(tmp_path / "a.transkr") == project_key(
        tmp_path / "x" / ".." / "a.transkr"
    )
    assert session_key("abc") == "session-abc"
