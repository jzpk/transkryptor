"""Model dokumentu transkrypcji.

Dokument to ciągły tekst z zakresami indeksu górnego, metadanymi (autor,
data i metryczka nagrania), mówcami akapitów oraz stanem zmian. Stan zmian jest licznikiem
rewizji: każda mutacja zwiększa ``revision``. Dwa znaczniki zapamiętują
rewizję ostatniego eksportu DOCX (:meth:`Document.mark_exported`) i ostatniego
zapisu pliku projektu (:meth:`Document.mark_saved`) - dokument może być
zapisany, ale niewyeksportowany, i odwrotnie.

Moduł nie odczytuje audio ani nie eksportuje plików.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from transkryptor.document.metadata import normalized
from transkryptor.document.speakers import (
    DEFAULT_SPEAKERS,
    Speaker,
    clean_assignments,
    shift_assignments,
)


@dataclass
class Document:
    """Dokument transkrypcji w pamięci bieżącej sesji.

    ``superscript_ranges`` to lista półotwartych zakresów znaków
    ``(start, end)`` sformatowanych indeksem górnym, posortowana i bez
    nakładających się elementów - niezmiennik pilnują konstruktor
    i :meth:`replace_all`. ``metadata`` to metryczka nagrania (klucze
    z ``document/metadata.py``) bez pustych wartości. ``speakers`` to lista
    mówców nagrania, a ``paragraph_speakers`` - indeks akapitu (kolejny
    fragment między znakami nowej linii) → klucz mówcy z tej listy.
    """

    text: str = ""
    superscript_ranges: list[tuple[int, int]] = field(default_factory=list)
    author: str = ""
    date: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    speakers: list[Speaker] = field(default_factory=lambda: list(DEFAULT_SPEAKERS))
    paragraph_speakers: dict[int, str] = field(default_factory=dict)
    revision: int = 0
    exported_revision: int = 0
    saved_revision: int = 0

    def __post_init__(self) -> None:
        self.superscript_ranges = clip_ranges(self.superscript_ranges, len(self.text))
        self.paragraph_speakers = clean_assignments(
            self.paragraph_speakers, self.text, self.speakers
        )

    @property
    def is_dirty(self) -> bool:
        """Czy od ostatniego eksportu wprowadzono zmiany."""
        return self.revision != self.exported_revision

    @property
    def is_unsaved(self) -> bool:
        """Czy od ostatniego zapisu projektu wprowadzono zmiany."""
        return self.revision != self.saved_revision

    def mark_exported(self) -> None:
        """Oznacza bieżącą rewizję jako wyeksportowaną."""
        self.exported_revision = self.revision

    def mark_saved(self) -> None:
        """Oznacza bieżącą rewizję jako zapisaną w pliku projektu."""
        self.saved_revision = self.revision

    def touch(self) -> None:
        """Zmiana stanu projektu poza tekstem (np. inne nagranie)."""
        self.revision += 1

    def set_metadata(self, author: str, date: str) -> None:
        """Ustawia autora i datę transkrypcji."""
        if author == self.author and date == self.date:
            return
        self.author = author
        self.date = date
        self.revision += 1

    def set_metadata_values(self, values: dict[str, str]) -> None:
        """Ustawia pola metryczki; puste wartości usuwają pole."""
        merged = normalized({**self.metadata, **values})
        if merged == self.metadata:
            return
        self.metadata = merged
        self.revision += 1

    def set_speakers(
        self, speakers: list[Speaker], renamed: dict[str, str] | None = None
    ) -> None:
        """Ustawia listę mówców.

        ``renamed`` (stary klucz → nowy) przepina akapity; przypisania
        mówców spoza nowej listy są usuwane.
        """
        renamed = renamed or {}
        assignments = clean_assignments(
            {i: renamed.get(key, key) for i, key in self.paragraph_speakers.items()},
            self.text,
            speakers,
        )
        if speakers == self.speakers and assignments == self.paragraph_speakers:
            return
        self.speakers = list(speakers)
        self.paragraph_speakers = assignments
        self.revision += 1

    def speaker(self, key: str) -> Speaker | None:
        return next((s for s in self.speakers if s.key == key), None)

    def replace_all(
        self,
        text: str,
        superscript_ranges: list[tuple[int, int]],
        paragraph_speakers: dict[int, str] | None = None,
    ) -> bool:
        """Zastępuje cały tekst i zakresy indeksu górnego (np. z edytora).

        Zakresy są normalizowane; ``paragraph_speakers`` (None = bez zmian
        przypisań) jest oczyszczane do akapitów tekstu i znanych mówców.
        Rewizja rośnie tylko przy faktycznej zmianie. Zwraca True, gdy
        dokument się zmienił.
        """
        ranges = clip_ranges(superscript_ranges, len(text))
        assignments = clean_assignments(
            (
                self.paragraph_speakers
                if paragraph_speakers is None
                else paragraph_speakers
            ),
            text,
            self.speakers,
        )
        if (
            text == self.text
            and ranges == self.superscript_ranges
            and assignments == self.paragraph_speakers
        ):
            return False
        self.text = text
        self.superscript_ranges = ranges
        self.paragraph_speakers = assignments
        self.revision += 1
        return True

    def replace(self, start: int, end: int, new_text: str) -> None:
        """Zastępuje ``text[start:end]`` przez ``new_text``.

        Zakresy indeksu górnego za edytowanym fragmentem są przesuwane,
        zakresy przecięte edycją obcinane, a wstawiony tekst nie dziedziczy
        formatowania. Usunięcie granicy akapitów scala je (zostaje mówca
        pierwszego), a wstawione akapity są bez mówcy.
        """
        if not 0 <= start <= end <= len(self.text):
            raise ValueError(f"Nieprawidłowy zakres edycji: ({start}, {end})")
        delta = len(new_text) - (end - start)
        self.paragraph_speakers = shift_assignments(
            self.paragraph_speakers,
            self.text[start:end],
            new_text,
            self.text.count("\n", 0, start),
        )
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
            self.superscript_ranges = normalize_ranges(
                self.superscript_ranges + [(start, end)]
            )
        else:
            self.superscript_ranges = _subtract(self.superscript_ranges, start, end)
        self.revision += 1


def normalize_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
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


def clip_ranges(ranges: list[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    """Normalizuje zakresy i przycina je do długości tekstu."""
    return normalize_ranges(
        [(max(start, 0), min(end, length)) for start, end in ranges]
    )


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
    return normalize_ranges(adjusted)


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
