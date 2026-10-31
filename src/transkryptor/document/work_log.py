"""Czas aktywnej pracy nad projektem zapisywany w pliku projektu (bez Qt).

``WorkLog`` (od schematu 7 projektu) to suma sekund pracy, długość nagrania
(gdy była znana) i dzienne wpisy: czas pracy danego dnia oraz pokrycie
nagrania tekstem przy pierwszej aktywności dnia - z niego liczony jest
postęp celu dziennego (``document/progress.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Ile dni pracy (wpisów dziennych) zostaje w projekcie.
MAX_DAYS = 366


@dataclass(frozen=True)
class WorkDay:
    """Praca w jednym dniu (data ISO ``RRRR-MM-DD``)."""

    date: str
    seconds: int = 0
    # Pokrycie nagrania tekstem (ms) przy pierwszej aktywności tego dnia.
    covered_start_ms: int = 0


@dataclass(frozen=True)
class WorkLog:
    """Czas aktywnej pracy nad projektem."""

    seconds: int = 0
    # Długość nagrania w ms (None - nagranie nie było jeszcze otwarte).
    audio_duration_ms: int | None = None
    days: tuple[WorkDay, ...] = ()

    def day(self, date: str) -> WorkDay | None:
        return next((day for day in self.days if day.date == date), None)

    def start_day(self, date: str, covered_ms: int) -> WorkLog:
        """Wpis dnia ``date`` (jeśli go nie ma) z pokryciem na początek dnia."""
        if self.day(date) is not None:
            return self
        days = (*self.days, WorkDay(date, 0, covered_ms))
        return replace(self, days=days[-MAX_DAYS:])

    def add(self, seconds: int, date: str, covered_ms: int = 0) -> WorkLog:
        """Dolicza ``seconds`` pracy do sumy i do dnia ``date``."""
        if seconds <= 0:
            return self
        log = self.start_day(date, covered_ms)
        days = tuple(
            replace(day, seconds=day.seconds + seconds) if day.date == date else day
            for day in log.days
        )
        return replace(log, seconds=log.seconds + seconds, days=days)

    def with_duration(self, duration_ms: int | None) -> WorkLog:
        if not duration_ms or duration_ms <= 0:
            return self
        return replace(self, audio_duration_ms=duration_ms)
