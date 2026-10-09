"""Plik projektu ``.transkr``: stan pracy nad nagraniem (bez Qt).

Projekt to jeden plik JSON (UTF-8) z polem ``schema_version``. Zawiera
tekst z zakresami indeksu górnego, autora, datę i metryczkę, odwołanie do
nagrania (ścieżka względna do pliku projektu, bezwzględna jako podpowiedź
i suma SHA-256 — bez osadzania audio), pozycję odtwarzania, pętlę A–B,
ostatni wynik ASR (tekst i segmenty z czasami i pewnością) oraz pozycje
przeglądu reguł (zakres w tekście, kod reguły i treść propozycji).

Zapis jest atomowy: plik tymczasowy w katalogu docelowym, ``fsync``
i ``os.replace`` — przerwany zapis nie psuje poprzedniej wersji. Odczyt
przechodzi przez :func:`migrate`, który podnosi starsze schematy do
bieżącego; nowa wersja schematu to nowy wpis w ``_MIGRATIONS``.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from transkryptor.errors import ProjectError
from transkryptor.i18n import tr

SCHEMA_VERSION = 1
PROJECT_SUFFIX = ".transkr"
_HASH_CHUNK = 1 << 20


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
class AsrSegment:
    start_s: float
    end_s: float
    text: str
    confidence: float


@dataclass(frozen=True)
class AsrDraft:
    """Ostatni wynik ASR — pozwala wstawić szkic ponownie bez transkrypcji."""

    text: str
    language: str = "pl"
    segments: tuple[AsrSegment, ...] = ()


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

    @property
    def word_count(self) -> int:
        return len(self.text.split())


# --- serializacja ---------------------------------------------------------------


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
                "segments": [
                    {
                        "start_s": s.start_s,
                        "end_s": s.end_s,
                        "text": s.text,
                        "confidence": s.confidence,
                    }
                    for s in state.asr.segments
                ],
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
    }


def dumps(state: ProjectState, project_path: Path | None = None) -> str:
    return json.dumps(to_dict(state, project_path), ensure_ascii=False, indent=1)


def from_dict(data: Any) -> ProjectState:
    """Odtwarza stan z JSON po migracji; błąd schematu → ``ProjectError``."""
    data = migrate(data)
    try:
        return _parse(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid() from exc


def loads(raw: str) -> ProjectState:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise _invalid() from exc
    return from_dict(data)


# --- migracje -------------------------------------------------------------------

# Wersja N → N+1. Migracja dostaje słownik w wersji N i zwraca słownik
# w wersji N+1 (z podbitym ``schema_version``); nie zmienia wejścia.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(data: Any) -> dict[str, Any]:
    """Podnosi projekt do bieżącej wersji schematu.

    Projekt z nowszej wersji aplikacji jest odrzucany zrozumiałym błędem —
    odczyt mógłby po cichu zgubić nieznane dane.
    """
    if not isinstance(data, dict):
        raise _invalid()
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _invalid()
    if version > SCHEMA_VERSION:
        raise ProjectError(
            user_message=tr(
                "project.error.newer", version=version, supported=SCHEMA_VERSION
            ),
            retry_hint=tr("project.error.newer.hint"),
        )
    while version < SCHEMA_VERSION:
        data = _MIGRATIONS[version](data)
        version = data["schema_version"]
    return data


# --- pliki ----------------------------------------------------------------------


def save_project(state: ProjectState, path: str | Path) -> None:
    """Zapisuje projekt atomowo; błąd zapisu → ``ProjectError``."""
    target = Path(path)
    write_atomic(target, dumps(state, target).encode("utf-8"))


def load_project(path: str | Path) -> ProjectState:
    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ProjectError(
            user_message=tr(
                "project.error.open", name=source.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("project.error.open.hint"),
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid(source.name) from exc
    try:
        return loads(text)
    except InvalidProjectError as error:
        raise _invalid(source.name) from error


def write_atomic(target: Path, payload: bytes, mode: int | None = None) -> None:
    """Plik tymczasowy w katalogu docelowym, ``fsync`` i ``os.replace``.

    ``tempfile`` tworzy plik z prawami ``0600``, a ``os.replace`` przenosi je
    na plik docelowy. Dlatego przed podmianą plik dostaje prawa ``mode``,
    a bez niego — prawa istniejącego pliku albo domyślne dla nowego
    (``0666`` z maską umask). Projekt na wspólnym udziale zostaje czytelny
    dla zespołu; autozapis podaje ``0o600``.
    """
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(temp_name, _target_mode(target) if mode is None else mode)
        os.replace(temp_name, target)
        temp_name = None
        _fsync_directory(target.parent)
    except OSError as exc:
        raise ProjectError(
            user_message=tr(
                "project.error.save", name=target.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("project.error.save.hint"),
        ) from exc
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def _target_mode(target: Path) -> int:
    """Prawa istniejącego pliku albo ``0666`` z maską umask dla nowego."""
    try:
        return stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _fsync_directory(directory: Path) -> None:
    """Utrwala wpis katalogu po ``os.replace`` (ext4/XFS); tylko POSIX."""
    if os.name != "posix":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # część systemów plików (np. udziały sieciowe) tego nie wspiera
    finally:
        os.close(fd)


def file_sha256(
    path: str | Path, should_cancel: Callable[[], bool] | None = None
) -> str:
    """Suma SHA-256 pliku; ``should_cancel`` przerywa liczenie (InterruptedError)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            if should_cancel is not None and should_cancel():
                raise InterruptedError(str(path))
            digest.update(chunk)
    return digest.hexdigest()


def audio_ref(path: str | Path) -> AudioRef:
    """Odwołanie do nagrania z sumą SHA-256 (plik musi istnieć)."""
    absolute = Path(path).resolve()
    return AudioRef(absolute_path=str(absolute), sha256=file_sha256(absolute))


def relative_audio_path(audio_path: str | Path, project_path: Path) -> str | None:
    """Ścieżka nagrania względem katalogu projektu (zapis POSIX).

    None, gdy ścieżki względnej nie da się zbudować (inny dysk w Windows).
    """
    try:
        relative = os.path.relpath(
            Path(audio_path).resolve(), Path(project_path).resolve().parent
        )
    except ValueError:
        return None
    return Path(relative).as_posix()


def resolve_audio(audio: AudioRef, project_path: Path | None) -> Path | None:
    """Istniejący plik nagrania: najpierw ścieżka względna, potem bezwzględna."""
    candidates: list[Path] = []
    if audio.relative_path and project_path is not None:
        candidates.append(
            Path(project_path).parent.joinpath(
                *PurePosixPath(audio.relative_path).parts
            )
        )
    candidates.append(Path(audio.absolute_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# --- parsowanie -----------------------------------------------------------------


class InvalidProjectError(ProjectError):
    """Plik nie jest poprawnym projektem (składnia albo schemat)."""


def _invalid(name: str = "") -> InvalidProjectError:
    return InvalidProjectError(
        user_message=(
            tr("project.error.invalid_named", name=name)
            if name
            else tr("project.error.invalid")
        ),
        retry_hint=tr("project.error.invalid.hint"),
    )


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
            segments=tuple(
                AsrSegment(
                    start_s=_float(s["start_s"]),
                    end_s=_float(s["end_s"]),
                    text=_str(s["text"]),
                    confidence=_float(s["confidence"]),
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
    metadata = _dict(document.get("metadata", {}))
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
