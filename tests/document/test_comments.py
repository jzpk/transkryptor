"""Komentarze recenzji: model i zapis w pliku projektu (faza 14, ACC-64)."""

import json
from typing import Any

import pytest

from transkryptor.document.comments import (
    Comment,
    Reply,
    check_comment,
    display_date,
    new_comment,
)
from transkryptor.document.project import (
    SCHEMA_VERSION,
    ProjectState,
    dumps,
    from_dict,
    loads,
    migrate,
)
from transkryptor.errors import ProjectError

COMMENT = Comment(
    id="c1",
    start=4,
    end=8,
    author="Weryfikator",
    created="2026-10-24T14:05",
    text="Raczej „buło”?",
    quote="było",
    replies=(Reply("Transkrybent", "2026-10-24T15:00", "Poprawione."),),
)


def test_new_comment_has_unique_id_and_date() -> None:
    first = new_comment(0, 3, "tak", "A", "uwaga")
    second = new_comment(0, 3, "tak", "A", "uwaga")
    assert first.id != second.id
    assert len(first.created) == len("2026-10-24T14:05")
    assert display_date("2026-10-24T14:05") == "2026-10-24 14:05"


def test_with_reply_appends_to_thread() -> None:
    reply = Reply("B", "2026-10-25T09:00", "Druga odpowiedź")
    assert COMMENT.with_reply(reply).replies == (*COMMENT.replies, reply)


def test_check_comment() -> None:
    check_comment(COMMENT, 8)
    # Fragment usunięty: komentarz zostaje jako punkt.
    check_comment(Comment("c2", 3, 3, "A", "", "x"), 3)
    with pytest.raises(ValueError):
        check_comment(COMMENT, 7)
    with pytest.raises(ValueError):
        check_comment(Comment("", 0, 0, "A", "", "x"), 0)


def test_project_round_trip() -> None:
    state = ProjectState(text="tak było", comments=(COMMENT,))
    restored = loads(dumps(state))
    assert restored.comments == (COMMENT,)
    assert json.loads(dumps(state))["schema_version"] == SCHEMA_VERSION == 6


def test_resolved_status_round_trip() -> None:
    from dataclasses import replace

    resolved = replace(COMMENT, resolved=True)
    state = ProjectState(text="tak było", comments=(resolved,))
    assert json.loads(dumps(state))["comments"][0]["resolved"] is True
    assert loads(dumps(state)).comments == (resolved,)
    # Otwarty komentarz zapisuje się jak w wersjach bez statusu.
    plain = json.loads(dumps(ProjectState(text="tak było", comments=(COMMENT,))))
    assert "resolved" not in plain["comments"][0]


def test_schema_5_gets_no_comments() -> None:
    data: dict[str, Any] = {"schema_version": 5, "document": {"text": "ab"}}
    migrated = migrate(data)
    assert migrated["schema_version"] == 6
    assert migrated["comments"] == []
    assert "comments" not in data  # wejście bez zmian
    assert from_dict(data).comments == ()


@pytest.mark.parametrize(
    "comment",
    [
        {"id": "c1", "start": 0, "end": 9, "text": "poza tekstem"},
        {"id": "c1", "start": 2, "end": 1, "text": "odwrócony"},
        {"id": "", "start": 0, "end": 1, "text": "bez id"},
        {"id": "c1", "start": 0, "end": 1},
        {"id": "c1", "start": 0, "end": 1, "text": "x", "replies": [{}]},
    ],
)
def test_invalid_comment_is_rejected(comment: dict[str, Any]) -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        "document": {"text": "ab"},
        "comments": [comment],
    }
    with pytest.raises(ProjectError):
        loads(json.dumps(data))


def test_duplicate_ids_are_rejected() -> None:
    comment = {"id": "c1", "start": 0, "end": 1, "text": "x"}
    data = {
        "schema_version": SCHEMA_VERSION,
        "document": {"text": "ab"},
        "comments": [comment, comment],
    }
    with pytest.raises(ProjectError):
        loads(json.dumps(data))
