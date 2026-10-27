"""Serializacja stanu projektu do JSON i odczyt z walidacją typów pól."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from transkryptor.document.anchors import Anchor, check_anchor
from transkryptor.document.comments import Comment, Reply, check_comment
from transkryptor.document.project.errors import invalid
from transkryptor.document.project.migrations import SCHEMA_VERSION, migrate
from transkryptor.document.project.model import (
    AsrContext,
    AsrDraft,
    AsrSegment,
    AsrWord,
    AudioRef,
    IgnoredWarning,
    PlayerState,
    ProjectState,
    ReviewEntry,
)
from transkryptor.document.project.paths import relative_audio_path
from transkryptor.document.speakers import Speaker, check_speakers, paragraph_count
from transkryptor.document.verification import normalized as verified_ranges


def to_dict(state: ProjectState, project_path: Path | None = None) -> dict[str, Any]:
    """Słownik JSON projektu; ścieżka względna liczona od ``project_path``."""
    audio: dict[str, Any] | None = None
    if state.audio is not None:
        relative = state.audio.relative_path
        if project_path is not None:
            relative = relative_audio_path(state.audio.absolute_path, project_path)
        audio = {
            "relative_path": relative,
            "absolute_path": state.audio.absolute_path,
            "sha256": state.audio.sha256,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "text": state.text,
            "superscript_ranges": [list(r) for r in state.superscript_ranges],
            "author": state.author,
            "date": state.date,
            "metadata": dict(state.metadata),
            "speakers": [
                {"key": s.key, "label": s.label, "role": s.role} for s in state.speakers
            ],
            "paragraph_speakers": [
                [index, key] for index, key in sorted(state.paragraph_speakers.items())
            ],
        },
        "exported": state.exported,
        "audio": audio,
        "player": {
            "position_ms": state.player.position_ms,
            "loop_a_ms": state.player.loop_a_ms,
            "loop_b_ms": state.player.loop_b_ms,
            "loop_active": state.player.loop_active,
        },
        "asr": (
            None
            if state.asr is None
            else {
                "text": state.asr.text,
                "language": state.asr.language,
                "model": state.asr.model,
                "segments": [_segment_dict(s) for s in state.asr.segments],
            }
        ),
        "review": [
            {
                "start": e.start,
                "end": e.end,
                "applied": e.applied,
                "code": e.code,
                "suggestion_start": e.suggestion_start,
                "suggestion_end": e.suggestion_end,
                "original": e.original,
                "replacement": e.replacement,
                "superscript_ranges": [list(r) for r in e.superscript_ranges],
                "source": e.source,
                "confidence": e.confidence,
                "message": e.message,
                "word": e.word,
                "word_start": e.word_start,
            }
            for e in state.review
        ],
        "asr_context": {
            "prompt": state.asr_context.prompt,
            "vocabulary": list(state.asr_context.vocabulary),
        },
        "ignored_warnings": [
            {"code": w.code, "start": w.start, "end": w.end, "text": w.text}
            for w in state.ignored_warnings
        ],
        "anchors": [_anchor_dict(a) for a in state.anchors],
        "comments": [_comment_dict(c) for c in state.comments],
        "verified": [list(r) for r in state.verified],
    }


def _segment_dict(segment: AsrSegment) -> dict[str, Any]:
    data: dict[str, Any] = {
        "start_s": segment.start_s,
        "end_s": segment.end_s,
        "text": segment.text,
        "confidence": segment.confidence,
    }
    if segment.words:
        data["words"] = [
            {
                "start_s": w.start_s,
                "end_s": w.end_s,
                "text": w.text,
                "probability": w.probability,
            }
            for w in segment.words
        ]
    if segment.speaker is not None:
        data["speaker"] = segment.speaker
    return data


def _anchor_dict(anchor: Anchor) -> dict[str, Any]:
    data: dict[str, Any] = {
        "start": anchor.start,
        "end": anchor.end,
        "start_ms": anchor.start_ms,
        "end_ms": anchor.end_ms,
        "source": anchor.source,
    }
    if anchor.probability is not None:
        data["probability"] = anchor.probability
    if anchor.edited:
        data["edited"] = True
    return data


def _comment_dict(comment: Comment) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": comment.id,
        "start": comment.start,
        "end": comment.end,
        "quote": comment.quote,
        "author": comment.author,
        "created": comment.created,
        "text": comment.text,
        "replies": [
            {"author": r.author, "created": r.created, "text": r.text}
            for r in comment.replies
        ],
    }
    if comment.resolved:
        data["resolved"] = True
    return data


def dumps(state: ProjectState, project_path: Path | None = None) -> str:
    return json.dumps(to_dict(state, project_path), ensure_ascii=False, indent=1)


def from_dict(data: Any) -> ProjectState:
    """Odtwarza stan z JSON po migracji; błąd schematu → ``ProjectError``."""
    data = migrate(data)
    try:
        return _parse(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise invalid() from exc


def loads(raw: str) -> ProjectState:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise invalid() from exc
    return from_dict(data)


def _parse(data: dict[str, Any]) -> ProjectState:
    document = _dict(data["document"])
    text = _str(document["text"])
    audio_data = data.get("audio")
    audio = None
    if audio_data is not None:
        audio_dict = _dict(audio_data)
        audio = AudioRef(
            absolute_path=_str(audio_dict["absolute_path"]),
            sha256=_str(audio_dict["sha256"]),
            relative_path=_optional_str(audio_dict.get("relative_path")),
        )
    player = _dict(data.get("player", {}))
    asr_data = data.get("asr")
    asr = None
    if asr_data is not None:
        asr_dict = _dict(asr_data)
        asr = AsrDraft(
            text=_str(asr_dict["text"]),
            language=_str(asr_dict.get("language", "pl")),
            model=_optional_str(asr_dict.get("model")),
            segments=tuple(
                AsrSegment(
                    start_s=_float(s["start_s"]),
                    end_s=_float(s["end_s"]),
                    text=_str(s["text"]),
                    confidence=_float(s["confidence"]),
                    words=tuple(
                        AsrWord(
                            start_s=_float(w["start_s"]),
                            end_s=_float(w["end_s"]),
                            text=_str(w["text"]),
                            probability=_float(w["probability"]),
                        )
                        for w in map(_dict, _list(s.get("words", [])))
                    ),
                    speaker=_optional_int(s.get("speaker")),
                )
                for s in map(_dict, _list(asr_dict.get("segments", [])))
            ),
        )
    review = tuple(
        ReviewEntry(
            start=_int(e["start"]),
            end=_int(e["end"]),
            applied=_bool(e["applied"]),
            code=_str(e["code"]),
            suggestion_start=_int(e["suggestion_start"]),
            suggestion_end=_int(e["suggestion_end"]),
            original=_str(e["original"]),
            replacement=_str(e["replacement"]),
            superscript_ranges=_ranges(e.get("superscript_ranges", [])),
            source=_str(e.get("source", "rule")),
            confidence=_float(e.get("confidence", 0.0)),
            message=_str(e.get("message", "")),
            word=_str(e.get("word", "")),
            word_start=_int(e.get("word_start", 0)),
        )
        for e in map(_dict, _list(data.get("review", [])))
    )
    ranges = _ranges(document.get("superscript_ranges", []))
    if any(end > len(text) for _start, end in ranges):
        raise ValueError("zakres indeksu górnego poza tekstem")
    if any(not 0 <= e.start <= e.end <= len(text) for e in review):
        raise ValueError("zakres przeglądu poza tekstem")
    ignored = tuple(
        IgnoredWarning(
            code=_str(w["code"]),
            start=_int(w["start"]),
            end=_int(w["end"]),
            text=_str(w.get("text", "")),
        )
        for w in map(_dict, _list(data.get("ignored_warnings", [])))
    )
    if any(not 0 <= w.start <= w.end <= len(text) for w in ignored):
        raise ValueError("zakres zignorowanego ostrzeżenia poza tekstem")
    anchors = tuple(
        Anchor(
            start=_int(a["start"]),
            end=_int(a["end"]),
            start_ms=_int(a["start_ms"]),
            end_ms=_int(a["end_ms"]),
            source=_str(a["source"]),
            probability=(
                None if a.get("probability") is None else _float(a["probability"])
            ),
            edited=_bool(a.get("edited", False)),
        )
        for a in map(_dict, _list(data.get("anchors", [])))
    )
    for anchor in anchors:
        check_anchor(anchor, len(text))
    comments = tuple(
        Comment(
            id=_str(c["id"]),
            start=_int(c["start"]),
            end=_int(c["end"]),
            quote=_str(c.get("quote", "")),
            author=_str(c.get("author", "")),
            created=_str(c.get("created", "")),
            text=_str(c["text"]),
            replies=tuple(
                Reply(
                    author=_str(r.get("author", "")),
                    created=_str(r.get("created", "")),
                    text=_str(r["text"]),
                )
                for r in map(_dict, _list(c.get("replies", [])))
            ),
            resolved=_bool(c.get("resolved", False)),
        )
        for c in map(_dict, _list(data.get("comments", [])))
    )
    for comment in comments:
        check_comment(comment, len(text))
    if len({comment.id for comment in comments}) != len(comments):
        raise ValueError("powtórzony identyfikator komentarza")
    speakers = tuple(
        Speaker(
            key=_str(entry["key"]),
            label=_str(entry.get("label", "")),
            role=_str(entry.get("role", "other")),
        )
        for entry in map(_dict, _list(document.get("speakers", [])))
    )
    check_speakers(speakers)
    keys = {speaker.key for speaker in speakers}
    paragraphs = paragraph_count(text)
    assignments: dict[int, str] = {}
    for item in _list(document.get("paragraph_speakers", [])):
        pair = _list(item)
        if len(pair) != 2:
            raise ValueError("przypisanie mówcy musi mieć dwa elementy")
        index, key = _int(pair[0]), _str(pair[1])
        if not 0 <= index < paragraphs or key not in keys or index in assignments:
            raise ValueError("nieprawidłowe przypisanie mówcy")
        assignments[index] = key
    metadata = _dict(document.get("metadata", {}))
    context = _dict(data.get("asr_context", {}))
    return ProjectState(
        text=text,
        superscript_ranges=ranges,
        author=_str(document.get("author", "")),
        date=_str(document.get("date", "")),
        metadata={_str(k): _str(v) for k, v in metadata.items()},
        exported=_bool(data.get("exported", False)),
        audio=audio,
        player=PlayerState(
            position_ms=max(0, _int(player.get("position_ms", 0))),
            loop_a_ms=_optional_int(player.get("loop_a_ms")),
            loop_b_ms=_optional_int(player.get("loop_b_ms")),
            loop_active=_bool(player.get("loop_active", False)),
        ),
        asr=asr,
        review=review,
        asr_context=AsrContext(
            prompt=_str(context.get("prompt", "")),
            vocabulary=tuple(map(_str, _list(context.get("vocabulary", [])))),
        ),
        ignored_warnings=ignored,
        anchors=anchors,
        speakers=speakers,
        paragraph_speakers=assignments,
        comments=comments,
        verified=verified_ranges(_ranges(data.get("verified", []))),
    )


def _dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("oczekiwano obiektu")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("oczekiwano listy")
    return value


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("oczekiwano tekstu")
    return value


def _optional_str(value: Any) -> str | None:
    return None if value is None else _str(value)


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError("oczekiwano wartości logicznej")
    return value


def _int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("oczekiwano liczby całkowitej")
    return value


def _optional_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("oczekiwano liczby")
    return float(value)


def _ranges(value: Any) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for item in _list(value):
        pair = _list(item)
        if len(pair) != 2:
            raise ValueError("zakres musi mieć dwa elementy")
        start, end = _int(pair[0]), _int(pair[1])
        if not 0 <= start < end:
            raise ValueError("nieprawidłowy zakres")
        ranges.append((start, end))
    return tuple(ranges)
