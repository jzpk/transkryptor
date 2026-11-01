"""Postęp pracy nad projektem: czas pracy, pokrycie nagrania i tempo (bez Qt).

Czas aktywnej pracy zapisany w projekcie to ``WorkLog``
(``document/work_log.py``); liczy go warstwa UI (``ui/work_time.py``) tylko
przy aktywności w oknie, z limitem bezczynności.

Pokrycie tekstem liczone jest z kotwic czasowych: zakresy segmentów i słów
szkicu ASR oraz czas między kolejnymi kotwicami (także ręcznymi znacznikami),
gdy między nimi w tekście jest coś więcej niż odstęp. Tekst bez kotwic nie
daje pokrycia - postęp pokazuje wtedy tylko liczba słów. Z tego samego
pokrycia mapa na fali dźwiękowej wyznacza luki (``document/coverage.py``).

:func:`project_stats` zbiera z ``ProjectState`` dane okna „Statystyki
projektu”, a :func:`stats_rows` - wiersze do eksportu CSV/XLSX.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from transkryptor.document.anchors import Anchor
from transkryptor.document.coverage import transcription_gaps
from transkryptor.document.project.model import ProjectState
from transkryptor.document.speakers import paragraph_spans
from transkryptor.document.verification import normalized
from transkryptor.i18n import tr

Range = tuple[int, int]


def covered_ranges(text: str, anchors: Iterable[Anchor]) -> tuple[Range, ...]:
    """Zakresy nagrania (ms) pokryte tekstem według kotwic czasowych."""
    ordered = sorted(anchors, key=lambda a: (a.start, a.end, a.start_ms))
    ranges: list[Range] = [
        (a.start_ms, a.end_ms) for a in ordered if a.end_ms > a.start_ms
    ]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.start_ms <= previous.end_ms:
            continue
        if text[previous.end : current.start].strip():
            ranges.append((previous.end_ms, current.start_ms))
    return normalized(ranges)


def total_ms(ranges: Iterable[Range]) -> int:
    return sum(end - start for start, end in ranges)


def covered_ms(text: str, anchors: Iterable[Anchor]) -> int:
    return total_ms(covered_ranges(text, anchors))


def words_by_speaker(state: ProjectState) -> tuple[tuple[str, int], ...]:
    """Słowa mówców (``klucz (opis)``); akapity bez mówcy osobno."""
    if not state.paragraph_speakers:
        return ()
    labels = {s.key: f"{s.key} ({s.description})" for s in state.speakers}
    counts: dict[str, int] = {}
    for index, (start, end) in enumerate(paragraph_spans(state.text)):
        words = len(state.text[start:end].split())
        if not words:
            continue
        key = state.paragraph_speakers.get(index)
        label = labels.get(key, key) if key else tr("stats.no_speaker")
        counts[label] = counts.get(label, 0) + words
    return tuple(counts.items())


@dataclass(frozen=True)
class ProjectStats:
    """Dane okna „Statystyki projektu”."""

    words: int
    work_seconds: int
    transcribed_ms: int
    verified_ms: int
    duration_ms: int | None = None
    words_by_speaker: tuple[tuple[str, int], ...] = ()
    open_comments: int = 0
    warnings: int = 0
    today_seconds: int = 0
    today_covered_ms: int = 0
    # Luki w transkrypcji (``document/coverage.py``); None - nieznana długość.
    gaps: tuple[Range, ...] | None = None

    def ratio(self, part_ms: int) -> float | None:
        """Część nagrania (0.0-1.0); None bez znanej długości nagrania."""
        if not self.duration_ms:
            return None
        return min(1.0, part_ms / self.duration_ms)

    @property
    def transcribed_ratio(self) -> float | None:
        return self.ratio(self.transcribed_ms)

    @property
    def verified_ratio(self) -> float | None:
        return self.ratio(self.verified_ms)

    @property
    def pace(self) -> float | None:
        """Minuty nagrania na godzinę pracy (None bez pracy lub pokrycia)."""
        if self.work_seconds < 60 or self.transcribed_ms <= 0:
            return None
        return (self.transcribed_ms / 60000) / (self.work_seconds / 3600)

    @property
    def remaining_seconds(self) -> int | None:
        """Szacowany czas pracy do końca transkrypcji przy obecnym tempie."""
        pace = self.pace
        if pace is None or not self.duration_ms:
            return None
        left_minutes = max(0, self.duration_ms - self.transcribed_ms) / 60000
        return round(left_minutes / pace * 3600)


def project_stats(
    state: ProjectState,
    today: str,
    warnings: int = 0,
    duration_ms: int | None = None,
    silence: Iterable[Range] = (),
) -> ProjectStats:
    """Statystyki projektu; ``duration_ms`` - długość nagrania, gdy znana.

    ``silence`` to cisza wykryta w nagraniu - nie jest luką w transkrypcji.
    """
    ranges = covered_ranges(state.text, state.anchors)
    covered = total_ms(ranges)
    day = state.work.day(today)
    duration = duration_ms or state.work.audio_duration_ms
    return ProjectStats(
        words=state.word_count,
        work_seconds=state.work.seconds,
        transcribed_ms=covered,
        verified_ms=total_ms(state.verified),
        duration_ms=duration,
        words_by_speaker=words_by_speaker(state),
        open_comments=sum(1 for c in state.comments if not c.resolved),
        warnings=warnings,
        today_seconds=day.seconds if day is not None else 0,
        today_covered_ms=max(0, covered - day.covered_start_ms) if day else 0,
        gaps=transcription_gaps(ranges, duration, silence) if duration else None,
    )


def format_duration(seconds: int) -> str:
    """Czas jako ``G:MM:SS`` (np. ``1:05:09``)."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_percent(ratio: float | None) -> str:
    return "-" if ratio is None else f"{ratio * 100:.0f}%"


def format_gaps(gaps: tuple[Range, ...] | None) -> str:
    """Liczba luk i ich łączny czas (``-`` bez znanej długości nagrania)."""
    if gaps is None:
        return "-"
    return tr(
        "stats.gaps.value",
        count=len(gaps),
        time=format_duration(total_ms(gaps) // 1000),
    )


def format_pace(pace: float | None) -> str:
    return "-" if pace is None else tr("stats.pace.value", pace=f"{pace:.1f}")


def stats_rows(stats: ProjectStats) -> Sequence[tuple[str, str | int]]:
    """Wiersze ``(nazwa, wartość)`` statystyk - okno i eksport CSV/XLSX."""
    rows: list[tuple[str, str | int]] = [
        (
            tr("stats.duration"),
            format_duration(stats.duration_ms // 1000) if stats.duration_ms else "-",
        ),
        (tr("stats.transcribed"), format_percent(stats.transcribed_ratio)),
        (tr("stats.transcribed_time"), format_duration(stats.transcribed_ms // 1000)),
        (tr("stats.gaps"), format_gaps(stats.gaps)),
        (tr("stats.verified"), format_percent(stats.verified_ratio)),
        (tr("stats.verified_time"), format_duration(stats.verified_ms // 1000)),
        (tr("stats.work_time"), format_duration(stats.work_seconds)),
        (tr("stats.today"), format_duration(stats.today_seconds)),
        (tr("stats.pace"), format_pace(stats.pace)),
        (
            tr("stats.remaining"),
            (
                "-"
                if stats.remaining_seconds is None
                else format_duration(stats.remaining_seconds)
            ),
        ),
        (tr("stats.words"), stats.words),
        (tr("stats.open_comments"), stats.open_comments),
        (tr("stats.warnings"), stats.warnings),
    ]
    rows.extend(
        (tr("stats.speaker_words", speaker=label), count)
        for label, count in stats.words_by_speaker
    )
    return rows
