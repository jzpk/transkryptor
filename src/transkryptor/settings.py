"""Model ustawień użytkownika (bez zależności od Qt).

Ustawienia są niemutowalnymi dataclassami z wartościami domyślnymi
i zakresami. Trwałość (``QSettings``) zapewnia warstwa UI
(``ui/settings_store.py``), która przekazuje tu płaski słownik klucz → wartość.
Odczyt nigdy nie rzuca wyjątku: każde brakujące, uszkodzone lub spoza zakresu
pole dostaje wartość domyślną, a pozostałe pola są zachowane (ACC-18).

Kolejne funkcje dodają własne pola i sekcje: nowe pole w dataclassie
i wpis w ``_FIELDS`` — bez zmian w mechanizmie zapisu.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    MetadataField,
    decode_fields,
)
from transkryptor.i18n import LANGUAGES
from transkryptor.notation.ellipsis import DEFAULT_ELLIPSIS_STYLE, EllipsisStyle

SCHEMA_VERSION = 1
SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True)
class PlayerSettings:
    """Ustawienia odtwarzacza (milisekundy)."""

    skip_ms: int = 3000
    auto_rewind_enabled: bool = True
    auto_rewind_ms: int = 1500
    segment_preroll_ms: int = 500


THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)

# Język interfejsu: ``system`` (za językiem systemu) albo kod z ``i18n.LANGUAGES``.
LANGUAGE_SYSTEM = "system"
LANGUAGE_CHOICES = (LANGUAGE_SYSTEM, *LANGUAGES)


@dataclass(frozen=True)
class AppearanceSettings:
    """Motyw (``system``, ``light``, ``dark``) i język interfejsu.

    Język działa od następnego uruchomienia programu.
    """

    theme: str = THEME_SYSTEM
    language: str = LANGUAGE_SYSTEM


@dataclass(frozen=True)
class EditorSettings:
    """Czcionka edytora; wartości puste/zerowe oznaczają czcionkę domyślną."""

    font_family: str = ""
    font_size_pt: int = 0


@dataclass(frozen=True)
class NotationSettings:
    """Konwencje zapisu notacji (wartości ``EllipsisStyle``)."""

    ellipsis_style: str = DEFAULT_ELLIPSIS_STYLE.value

    @property
    def ellipsis(self) -> EllipsisStyle:
        return EllipsisStyle(self.ellipsis_style)


@dataclass(frozen=True)
class ProjectSettings:
    """Autozapis bieżącej pracy (sekundy)."""

    autosave_enabled: bool = True
    autosave_interval_s: int = 60


@dataclass(frozen=True)
class MetadataSettings:
    """Pola metryczki zespołu: JSON z ``document.metadata.encode_fields``.

    Pusty napis oznacza zestaw domyślny.
    """

    fields_spec: str = ""

    @property
    def fields(self) -> tuple[MetadataField, ...]:
        decoded = decode_fields(self.fields_spec)
        return decoded if decoded is not None else DEFAULT_FIELDS


@dataclass(frozen=True)
class Settings:
    player: PlayerSettings = field(default_factory=PlayerSettings)
    editor: EditorSettings = field(default_factory=EditorSettings)
    notation: NotationSettings = field(default_factory=NotationSettings)
    project: ProjectSettings = field(default_factory=ProjectSettings)
    metadata: MetadataSettings = field(default_factory=MetadataSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)


@dataclass(frozen=True)
class _Field:
    """Opis pola: sekcja, nazwa atrybutu, typ i zakres dopuszczalnych wartości."""

    section: str
    name: str
    kind: type
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] | None = None
    validate: Callable[[str], bool] | None = None

    @property
    def key(self) -> str:
        return f"{self.section}/{self.name}"


SKIP_RANGE_MS = (500, 30_000)
AUTO_REWIND_RANGE_MS = (0, 10_000)
SEGMENT_PREROLL_RANGE_MS = (0, 5_000)
FONT_SIZE_RANGE_PT = (6, 48)  # 0 = domyślny, poza zakresem
AUTOSAVE_INTERVAL_RANGE_S = (30, 600)
ELLIPSIS_STYLES = tuple(style.value for style in EllipsisStyle)

_FIELDS: tuple[_Field, ...] = (
    _Field("player", "skip_ms", int, *SKIP_RANGE_MS),
    _Field("player", "auto_rewind_enabled", bool),
    _Field("player", "auto_rewind_ms", int, *AUTO_REWIND_RANGE_MS),
    _Field("player", "segment_preroll_ms", int, *SEGMENT_PREROLL_RANGE_MS),
    _Field("editor", "font_family", str),
    _Field("editor", "font_size_pt", int, *FONT_SIZE_RANGE_PT),
    _Field("notation", "ellipsis_style", str, choices=ELLIPSIS_STYLES),
    _Field("project", "autosave_enabled", bool),
    _Field("project", "autosave_interval_s", int, *AUTOSAVE_INTERVAL_RANGE_S),
    _Field(
        "metadata",
        "fields_spec",
        str,
        validate=lambda raw: decode_fields(raw) is not None,
    ),
    _Field("appearance", "theme", str, choices=THEMES),
    _Field("appearance", "language", str, choices=LANGUAGE_CHOICES),
)


def to_mapping(settings: Settings) -> dict[str, object]:
    """Spłaszcza ustawienia do słownika ``sekcja/pole`` → wartość."""
    mapping: dict[str, object] = {SCHEMA_VERSION_KEY: SCHEMA_VERSION}
    for spec in _FIELDS:
        mapping[spec.key] = getattr(getattr(settings, spec.section), spec.name)
    return mapping


def from_mapping(mapping: Mapping[str, Any]) -> Settings:
    """Odtwarza ustawienia ze słownika, zastępując błędne pola domyślnymi.

    Akceptuje też wartości tekstowe (``"3000"``, ``"true"``) — tak zwraca je
    ``QSettings`` w formacie INI. Nieznane klucze są ignorowane.
    """
    sections: dict[str, dict[str, object]] = {
        "player": {},
        "editor": {},
        "notation": {},
        "project": {},
        "metadata": {},
        "appearance": {},
    }
    for spec in _FIELDS:
        if spec.key not in mapping:
            continue
        value = _coerce(spec, mapping[spec.key])
        if value is not None:
            sections[spec.section][spec.name] = value
    return Settings(
        player=replace(PlayerSettings(), **sections["player"]),  # type: ignore[arg-type]
        editor=replace(EditorSettings(), **sections["editor"]),  # type: ignore[arg-type]
        notation=replace(
            NotationSettings(), **sections["notation"]  # type: ignore[arg-type]
        ),
        project=replace(
            ProjectSettings(), **sections["project"]  # type: ignore[arg-type]
        ),
        metadata=replace(
            MetadataSettings(), **sections["metadata"]  # type: ignore[arg-type]
        ),
        appearance=replace(
            AppearanceSettings(), **sections["appearance"]  # type: ignore[arg-type]
        ),
    )


def _coerce(spec: _Field, raw: object) -> object | None:
    """Zwraca poprawną wartość pola albo None (→ wartość domyślna)."""
    if spec.kind is bool:
        return _coerce_bool(raw)
    if spec.kind is str:
        if not isinstance(raw, str):
            return None
        if spec.choices is not None and raw not in spec.choices:
            return None
        if spec.validate is not None and not spec.validate(raw):
            return None
        return raw
    number = _coerce_int(raw)
    if number is None:
        return None
    if spec.name == "font_size_pt" and number == 0:
        return 0
    if spec.minimum is not None and number < spec.minimum:
        return None
    if spec.maximum is not None and number > spec.maximum:
        return None
    return number


def _coerce_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
    return None


def _coerce_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


RECENT_PROJECTS_LIMIT = 8


def push_recent(
    paths: list[str], path: str, limit: int = RECENT_PROJECTS_LIMIT
) -> list[str]:
    """Lista ostatnich projektów z ``path`` na początku, bez duplikatów."""
    return [path, *(p for p in paths if p != path)][:limit]
