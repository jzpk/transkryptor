"""Model dokumentu transkrypcji.

Dokument to ciągły tekst z zakresami indeksu górnego, metadanymi (autor,
data) oraz stanem zmian od ostatniego eksportu. Stan zmian jest licznikiem
rewizji: każda mutacja zwiększa ``revision``, a moduł eksportu po udanym
zapisie wywołuje :meth:`Document.mark_exported`.

Moduł nie odczytuje audio ani nie eksportuje plików.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Document:
    """Dokument transkrypcji w pamięci bieżącej sesji.

    ``superscript_ranges`` to lista półotwartych zakresów znaków
    ``(start, end)`` sformatowanych indeksem górnym, posortowana i bez
    nakładających się elementów.
    """

    text: str = ""
    superscript_ranges: list[tuple[int, int]] = field(default_factory=list)
    author: str = ""
    date: str = ""
    revision: int = 0
    exported_revision: int = 0

    @property
    def is_dirty(self) -> bool:
        """Czy od ostatniego eksportu wprowadzono zmiany."""
        return self.revision != self.exported_revision

    def mark_exported(self) -> None:
        """Oznacza bieżącą rewizję jako wyeksportowaną."""
        self.exported_revision = self.revision

    def set_metadata(self, author: str, date: str) -> None:
        """Ustawia autora i datę transkrypcji."""
        if author == self.author and date == self.date:
            return
        self.author = author
        self.date = date
        self.revision += 1

    def replace(self, start: int, end: int, new_text: str) -> None:
        """Zastępuje ``text[start:end]`` przez ``new_text``.

        Zakresy indeksu górnego za edytowanym fragmentem są przesuwane,
        zakresy przecięte edycją obcinane, a wstawiony tekst nie dziedziczy
        formatowania.
        """
        if not 0 <= start <= end <= len(self.text):
            raise ValueError(f"Nieprawidłowy zakres edycji: ({start}, {end})")
        delta = len(new_text) - (end - start)
        self.text = self.text[:start] + new_text + self.text[end:]
        self.superscript_ranges = _adjust_ranges(
            self.superscript_ranges, start, end, len(new_text), delta
        )
        self.revision += 1

    def set_superscript(self, start: int, end: int, enabled: bool = True) -> None:
        """Włącza lub wyłącza indeks górny na zakresie ``(start, end)``."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError(f"Nieprawidłowy zakres formatowania: ({start}, {end})")
        if enabled:
            self.superscript_ranges = _normalize(
                self.superscript_ranges + [(start, end)]
            )
        else:
            self.superscript_ranges = _subtract(self.superscript_ranges, start, end)
        self.revision += 1


def _normalize(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sortuje zakresy i scala nakładające się lub przyległe."""
    result: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def _adjust_ranges(
    ranges: list[tuple[int, int]], start: int, end: int, inserted: int, delta: int
) -> list[tuple[int, int]]:
    """Aktualizuje zakresy po zastąpieniu ``text[start:end]`` nowym tekstem."""
    adjusted: list[tuple[int, int]] = []
    for range_start, range_end in ranges:
        if range_end <= start:
            adjusted.append((range_start, range_end))
        elif range_start >= end:
            adjusted.append((range_start + delta, range_end + delta))
        else:
            # Zakres przecięty edycją: zachowujemy części poza edytowanym
            # fragmentem; wstawiony tekst nie jest indeksem górnym.
            if range_start < start:
                adjusted.append((range_start, start))
            if range_end > end:
                adjusted.append((start + inserted, range_end + delta))
    return _normalize(adjusted)


def _subtract(
    ranges: list[tuple[int, int]], start: int, end: int
) -> list[tuple[int, int]]:
    """Usuwa formatowanie z zakresu ``(start, end)`` we wszystkich zakresach."""
    result: list[tuple[int, int]] = []
    for range_start, range_end in ranges:
        if range_end <= start or range_start >= end:
            result.append((range_start, range_end))
            continue
        if range_start < start:
            result.append((range_start, start))
        if range_end > end:
            result.append((end, range_end))
    return result
