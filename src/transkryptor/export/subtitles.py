"""Eksport napisów SRT i WebVTT z czasami z kotwic (``export/timeline.py``).

Każda jednostka czasowa to jeden napis z prefiksem mówcy: w SRT ``B: …``,
w WebVTT znacznik głosu ``<v B>…``. Indeks górny jak w TXT.
"""

from __future__ import annotations

from pathlib import Path

from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.superscript import render_runs
from transkryptor.export.text_export import speaker_prefix
from transkryptor.export.timeline import build_units


def timestamp(ms: int, separator: str) -> str:
    """``HH:MM:SS,mmm`` (SRT) albo ``HH:MM:SS.mmm`` (WebVTT)."""
    seconds, millis = divmod(max(ms, 0), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def render_srt(
    document: ExportDocument, options: ExportOptions, report: ExportReport
) -> str:
    cues: list[str] = []
    unmapped: set[str] = set()
    for index, unit in enumerate(build_units(document, options.untimed, report), 1):
        key = unit.speaker.key if unit.speaker is not None else None
        text = render_runs(unit.runs, options.superscript, unmapped)
        cues.append(
            f"{index}\n{timestamp(unit.start_ms, ',')} --> "
            f"{timestamp(unit.end_ms, ',')}\n{speaker_prefix(key)}{text}\n"
        )
    report.warn_unmapped(unmapped)
    return "\n".join(cues)


def _vtt_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_vtt(
    document: ExportDocument, options: ExportOptions, report: ExportReport
) -> str:
    blocks = ["WEBVTT", ""]
    title = document.title.replace("-->", "->")
    blocks += [f"NOTE {title}", ""]
    unmapped: set[str] = set()
    for unit in build_units(document, options.untimed, report):
        text = _vtt_escape(render_runs(unit.runs, options.superscript, unmapped))
        if unit.speaker is not None:
            text = f"<v {_vtt_escape(unit.speaker.key)}>{text}"
        blocks += [
            f"{timestamp(unit.start_ms, '.')} --> {timestamp(unit.end_ms, '.')}",
            text,
            "",
        ]
    report.warn_unmapped(unmapped)
    return "\n".join(blocks)


def write_srt(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    path.write_text(render_srt(document, options, report), encoding="utf-8")


def write_vtt(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    path.write_text(render_vtt(document, options, report), encoding="utf-8")
