"""Jednostki czasowe dla formatów z czasami (ELAN, Praat, SRT, WebVTT).

Jednostka to fragment akapitu z czasem początku i końca. Akapity są
dzielone na początkach kotwic segmentów ASR i ręcznych znaczników czasu
(``document/anchors.py``; kotwice słów nie dzielą tekstu). Czas początku
pochodzi z kotwicy na początku fragmentu, a czas końca — z końca segmentu
w obrębie fragmentu albo z początku następnej jednostki.

Znacznik czasu wiersza szkicu ASR (``[00:29]``) na początku albo końcu
fragmentu jest pomijany — czas jest w tych formatach jawny. Fragment bez czasu (np. dopisany ręcznie albo przeniesiony do
innego akapitu) dostaje czas interpolowany liniowo po pozycji znaku między
sąsiednimi znanymi punktami — albo jest pomijany (opcja ``untimed``). Za ostatnim znanym czasem
czas jest szacowany z tempa mowy (``ESTIMATED_MS_PER_CHAR``). Fragmenty
z czasem wyznaczonym i pominięte trafiają do raportu eksportu (ACC-54).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from transkryptor.document.anchors import MANUAL, SEGMENT, Anchor
from transkryptor.document.speakers import Speaker
from transkryptor.errors import ExportError
from transkryptor.export.model import ExportDocument, ExportRun, slice_runs, split_runs
from transkryptor.export.options import UNTIMED_SKIP, ExportReport
from transkryptor.i18n import tr

EXCERPT_LENGTH = 40
# Znacznik czasu wiersza szkicu ASR (``[01:23]``, ``[1:02:03]``) — czas jest
# w formatach z czasami jawny, więc znacznik nie trafia do adnotacji.
_LINE_TIME_RE = re.compile(r"\[\d{1,2}(?::\d{2}){1,2}\]\s*")
_TRAILING_TIME_RE = re.compile(r"\s*\[\d{1,2}(?::\d{2}){1,2}\]\s*$")
# Szacunek tempa mowy za ostatnią kotwicą: ok. 15 znaków na sekundę.
ESTIMATED_MS_PER_CHAR = 65


@dataclass(frozen=True)
class TimedUnit:
    start: int  # zakres tekstu bez otaczających odstępów
    end: int
    start_ms: int
    end_ms: int
    speaker: Speaker | None
    runs: tuple[ExportRun, ...]
    interpolated: bool = False

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass
class _Draft:
    start: int
    end: int
    speaker: Speaker | None
    start_ms: int | None
    end_ms: int | None


def build_units(
    document: ExportDocument, untimed: str, report: ExportReport
) -> list[TimedUnit]:
    """Jednostki w kolejności tekstu; brak kotwic → ``ExportError``."""
    anchors = [a for a in document.anchors if a.source in (SEGMENT, MANUAL)]
    if not anchors:
        raise ExportError(
            user_message=tr("export.error.no_times"),
            retry_hint=tr("export.error.no_times.hint"),
        )
    drafts = _drafts(document, anchors)
    points = _known_points(drafts, anchors)
    runs = split_runs(document.text, document.superscript_ranges)
    units: list[TimedUnit] = []
    interpolated: list[str] = []
    skipped: list[str] = []
    for draft in drafts:
        excerpt = _excerpt(document.text[draft.start : draft.end])
        start_ms, end_ms = draft.start_ms, draft.end_ms
        missing = start_ms is None or end_ms is None
        if missing and untimed == UNTIMED_SKIP:
            skipped.append(excerpt)
            continue
        if start_ms is None:
            start_ms = _interpolate(points, draft.start)
        if end_ms is None:
            end_ms = _interpolate(points, draft.end)
        if missing:
            interpolated.append(f"{format_clock(start_ms)} {excerpt}")
        if units and start_ms < units[-1].start_ms:
            start_ms = units[-1].start_ms
        end_ms = max(end_ms, start_ms + 1)
        units.append(
            TimedUnit(
                draft.start,
                draft.end,
                start_ms,
                end_ms,
                draft.speaker,
                slice_runs(document.text, runs, draft.start, draft.end),
                interpolated=missing,
            )
        )
    report.warn_fragments("export.report.interpolated", interpolated)
    report.warn_fragments("export.report.skipped", skipped)
    return units


def _drafts(document: ExportDocument, anchors: list[Anchor]) -> list[_Draft]:
    starts = sorted(anchors, key=lambda a: (a.start, a.source != MANUAL))
    start_positions = [a.start for a in starts]
    segments = sorted((a for a in anchors if a.source == SEGMENT), key=lambda a: a.end)
    segment_ends = [a.end for a in segments]
    text = document.text
    drafts: list[_Draft] = []
    for paragraph in document.paragraphs:
        lo = bisect_right(start_positions, paragraph.start)
        hi = bisect_left(start_positions, paragraph.end)
        cuts = [paragraph.start, *dict.fromkeys(start_positions[lo:hi]), paragraph.end]
        pieces: list[_Draft] = []
        for cut, next_cut in zip(cuts, cuts[1:], strict=False):
            piece = text[cut:next_cut]
            start = cut + len(piece) - len(piece.lstrip())
            marker = _LINE_TIME_RE.match(text, start, next_cut)
            if marker is not None:
                start = marker.end()
            # Znacznik tuż przed następną kotwicą (scalone wiersze szkicu).
            stripped = _TRAILING_TIME_RE.sub("", text[start:next_cut]).rstrip()
            if not stripped:
                continue
            end = start + len(stripped)
            pieces.append(
                _Draft(
                    start,
                    end,
                    paragraph.speaker,
                    _start_time(starts, start_positions, cut, start),
                    _end_time(segments, segment_ends, start, end, next_cut),
                )
            )
        drafts += pieces
    # Brak końca: początek następnej jednostki, jeśli jest znany.
    for draft, following in zip(drafts, drafts[1:], strict=False):
        if draft.end_ms is None and following.start_ms is not None:
            draft.end_ms = following.start_ms
    return drafts


def _start_time(
    starts: list[Anchor], positions: list[int], cut: int, start: int
) -> int | None:
    """Kotwica zaczynająca się między cięciem a pierwszym znakiem fragmentu."""
    lo = bisect_left(positions, cut)
    hi = bisect_right(positions, start)
    candidates = starts[lo:hi]
    if not candidates:
        return None
    manual = [a for a in candidates if a.source == MANUAL]
    return (manual or candidates)[-1].start_ms


def _end_time(
    segments: list[Anchor], ends: list[int], start: int, end: int, next_cut: int
) -> int | None:
    """Koniec segmentu, który kończy się w obrębie fragmentu (z odstępami)."""
    lo = bisect_left(ends, start + 1)
    hi = bisect_right(ends, next_cut)
    inside = [a for a in segments[lo:hi] if a.start < end]
    return max((a.end_ms for a in inside), default=None)


def _known_points(drafts: list[_Draft], anchors: list[Anchor]) -> list[tuple[int, int]]:
    """Znane pary (pozycja w tekście, czas) do interpolacji, rosnąco."""
    points: dict[int, int] = {0: 0}
    for anchor in anchors:
        points.setdefault(anchor.start, anchor.start_ms)
        if anchor.source == SEGMENT:
            points.setdefault(anchor.end, anchor.end_ms)
    for draft in drafts:
        if draft.start_ms is not None:
            points.setdefault(draft.start, draft.start_ms)
        if draft.end_ms is not None:
            points.setdefault(draft.end, draft.end_ms)
    return sorted(points.items())


def _interpolate(points: list[tuple[int, int]], position: int) -> int:
    """Czas dla pozycji między sąsiednimi znanymi punktami (za ostatnim — szacunek).

    ``points`` zawiera zawsze punkt ``(0, 0)``.
    """
    index = bisect_left(points, (position, -1))
    if index < len(points) and points[index][0] == position:
        return points[index][1]
    p1, t1 = points[index - 1]
    if index == len(points):
        return t1 + (position - p1) * ESTIMATED_MS_PER_CHAR
    p2, t2 = points[index]
    return round(t1 + (t2 - t1) * (position - p1) / (p2 - p1))


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > EXCERPT_LENGTH:
        text = text[: EXCERPT_LENGTH - 1] + "…"
    return tr("export.report.excerpt", text=text)


def format_clock(ms: int) -> str:
    """``mm:ss`` albo ``h:mm:ss`` dla raportu."""
    seconds = ms // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class Tier:
    """Warstwa formatu z czasami: mówca (albo „bez mówcy”) i jego jednostki."""

    name: str
    participant: str
    units: tuple[TimedUnit, ...]


def tiers(document: ExportDocument, units: list[TimedUnit]) -> list[Tier]:
    """Warstwa na mówcę z listy (także pusta) i warstwa jednostek bez mówcy.

    Dokument bez mówców ma jedną warstwę „transkrypcja”.
    """
    if not document.uses_speakers:
        return [Tier(tr("export.tier.transcription"), "", tuple(units))]
    result = [
        Tier(
            speaker.key,
            speaker.description,
            tuple(
                u
                for u in units
                if u.speaker is not None and u.speaker.key == speaker.key
            ),
        )
        for speaker in document.speakers
    ]
    unassigned = tuple(u for u in units if u.speaker is None)
    if unassigned:
        result.append(Tier(tr("export.tier.no_speaker"), "", unassigned))
    return result
