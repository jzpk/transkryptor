"""Eksport do zwykłego tekstu (TXT, UTF-8, bez czasów).

Na początku metryczka („Etykieta: wartość”, z legendą mówców) i akapit
„Autor: … Data: …”, po pustym wierszu - akapity tekstu, każdy w osobnym
wierszu, z prefiksem mówcy ``B: ``. Indeks górny zapisuje
``export/superscript.py``.
"""

from __future__ import annotations

from pathlib import Path

from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.superscript import render_runs


def speaker_prefix(key: str | None) -> str:
    return f"{key}: " if key else ""


def render_text(
    document: ExportDocument, options: ExportOptions, report: ExportReport
) -> str:
    lines = [f"{label}: {value}" for label, value in document.header_rows()]
    if document.author_line:
        lines.append(document.author_line)
    if lines:
        lines.append("")
    unmapped: set[str] = set()
    for paragraph in document.paragraphs:
        key = paragraph.speaker.key if paragraph.speaker is not None else None
        lines.append(
            speaker_prefix(key)
            + render_runs(paragraph.runs, options.superscript, unmapped)
        )
    report.warn_unmapped(unmapped)
    return "\n".join(lines) + "\n"


def write_txt(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    path.write_text(render_text(document, options, report), encoding="utf-8")
