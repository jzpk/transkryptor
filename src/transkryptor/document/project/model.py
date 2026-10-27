"""Stan projektu ``.transkr``: niezmienne dataclassy bez serializacji i I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from transkryptor.document.anchors import Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.speakers import DEFAULT_SPEAKERS, Speaker
from transkryptor.i18n import tr

PROJECT_SUFFIX = ".transkr"


def file_dialog_filter() -> str:
    """Filtr okna wyboru pliku projektu."""
    return tr("project.file_filter", pattern=f"*{PROJECT_SUFFIX}")


@dataclass(frozen=True)
class AudioRef:
    """Odwołanie do nagrania; ``relative_path`` w zapisie POSIX (``/``)."""

    absolute_path: str
    sha256: str
    relative_path: str | None = None

    @property
    def name(self) -> str:
        return PurePosixPath(Path(self.absolute_path).as_posix()).name


@dataclass(frozen=True)
class PlayerState:
    position_ms: int = 0
    loop_a_ms: int | None = None
    loop_b_ms: int | None = None
    loop_active: bool = False


@dataclass(frozen=True)
class AsrWord:
    start_s: float
    end_s: float
    text: str
    probability: float


@dataclass(frozen=True)
class AsrSegment:
    start_s: float
    end_s: float
    text: str
    confidence: float
    # Słowa z czasami (schemat 4; puste, gdy ASR ich nie liczył).
    words: tuple[AsrWord, ...] = ()
    # Numer mówcy z podziału na mówców (schemat 5; None bez diaryzacji).
    speaker: int | None = None


@dataclass(frozen=True)
class AsrDraft:
    """Ostatni wynik ASR - pozwala wstawić szkic ponownie bez transkrypcji."""

    text: str
    language: str = "pl"
    segments: tuple[AsrSegment, ...] = ()
    # Klucz modelu, którym obliczono szkic (None w projektach sprzed 0.4).
    model: str | None = None


@dataclass(frozen=True)
class AsrContext:
    """Kontekst nagrania i słownik projektu przekazywane do ASR (REQ-21)."""

    prompt: str = ""
    vocabulary: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewEntry:
    """Pozycja przeglądu reguł.

    ``start``/``end`` to bieżący zakres fragmentu w tekście dokumentu
    (oryginał propozycji albo wstawiona zamiana). Pozostałe pola opisują
    propozycję tak, jak zwróciła ją reguła (pozycje względem szkicu).
    """

    start: int
    end: int
    applied: bool
    code: str
    suggestion_start: int
    suggestion_end: int
    original: str
    replacement: str
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    source: str = "rule"
    confidence: float = 0.0
    message: str = ""
    word: str = ""
    word_start: int = 0


@dataclass(frozen=True)
class IgnoredWarning:
    """Ostrzeżenie walidatora zignorowane w jednym miejscu („Ignoruj tutaj”).

    ``start``/``end`` to zakres w tekście dokumentu, ``text`` - treść
    fragmentu w chwili zapisu (kontrola przy odtwarzaniu).
    """

    code: str
    start: int
    end: int
    text: str = ""


@dataclass(frozen=True)
class ProjectState:
    text: str = ""
    superscript_ranges: tuple[tuple[int, int], ...] = ()
    author: str = ""
    date: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    exported: bool = False
    audio: AudioRef | None = None
    player: PlayerState = field(default_factory=PlayerState)
    asr: AsrDraft | None = None
    review: tuple[ReviewEntry, ...] = ()
    asr_context: AsrContext = field(default_factory=AsrContext)
    ignored_warnings: tuple[IgnoredWarning, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    speakers: tuple[Speaker, ...] = DEFAULT_SPEAKERS
    paragraph_speakers: dict[int, str] = field(default_factory=dict)
    comments: tuple[Comment, ...] = ()
    # Sprawdzone zakresy nagrania (ms), posortowane i rozłączne.
    verified: tuple[tuple[int, int], ...] = ()

    @property
    def word_count(self) -> int:
        return len(self.text.split())
