"""Eksport do Praat (``.TextGrid``, format długi, UTF-8) z czasami z kotwic.

Warstwa przedziałów (``IntervalTier``) na mówcę. Praat wymaga, by przedziały
warstwy pokrywały cały czas bez luk i nakładania - luki są wypełniane
pustymi przedziałami, a jednostka nachodząca na poprzednią w tej samej
warstwie zaczyna się w chwili jej końca.
"""

from __future__ import annotations

from pathlib import Path

from transkryptor.export.model import ExportDocument
from transkryptor.export.options import ExportOptions, ExportReport
from transkryptor.export.superscript import render_runs
from transkryptor.export.timeline import Tier, build_units, tiers


def _quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.3f}".rstrip("0").rstrip(".") or "0"


def _intervals(
    tier: Tier, xmax: int, mode: str, unmapped: set[str]
) -> list[tuple[int, int, str]]:
    intervals: list[tuple[int, int, str]] = []
    position = 0
    for unit in sorted(tier.units, key=lambda u: u.start_ms):
        start, end = max(unit.start_ms, position), unit.end_ms
        if end <= start:
            continue
        if start > position:
            intervals.append((position, start, ""))
        intervals.append((start, end, render_runs(unit.runs, mode, unmapped)))
        position = end
    if position < xmax or not intervals:
        intervals.append((position, max(xmax, position + 1), ""))
    return intervals


def render_textgrid(
    document: ExportDocument, options: ExportOptions, report: ExportReport
) -> str:
    units = build_units(document, options.untimed, report)
    layers = tiers(document, units)
    xmax = max((unit.end_ms for unit in units), default=1)
    unmapped: set[str] = set()
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0 ",
        f"xmax = {_seconds(xmax)} ",
        "tiers? <exists> ",
        f"size = {len(layers)} ",
        "item []: ",
    ]
    for number, tier in enumerate(layers, 1):
        intervals = _intervals(tier, xmax, options.superscript, unmapped)
        lines += [
            f"    item [{number}]:",
            '        class = "IntervalTier" ',
            f"        name = {_quote(tier.name)} ",
            "        xmin = 0 ",
            f"        xmax = {_seconds(xmax)} ",
            f"        intervals: size = {len(intervals)} ",
        ]
        for index, (start, end, text) in enumerate(intervals, 1):
            lines += [
                f"        intervals [{index}]:",
                f"            xmin = {_seconds(start)} ",
                f"            xmax = {_seconds(end)} ",
                f"            text = {_quote(text)} ",
            ]
    report.warn_unmapped(unmapped)
    return "\n".join(lines) + "\n"


def write_textgrid(
    document: ExportDocument, path: Path, options: ExportOptions, report: ExportReport
) -> None:
    path.write_text(render_textgrid(document, options, report), encoding="utf-8")
