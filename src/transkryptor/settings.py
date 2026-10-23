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

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from transkryptor.asr.engine import DEVICES
from transkryptor.asr.models import DEFAULT_MODEL, MODELS
from transkryptor.document.metadata import (
    DEFAULT_FIELDS,
    MetadataField,
    decode_fields,
)
from transkryptor.export.options import UNTIMED_INTERPOLATE, UNTIMED_MODES
from transkryptor.export.superscript import MODES as SUPERSCRIPT_MODES
from transkryptor.export.superscript import UNICODE
from transkryptor.i18n import LANGUAGES
from transkryptor.notation.ellipsis import DEFAULT_ELLIPSIS_STYLE, EllipsisStyle
from transkryptor.notation.validator import enabled_codes

SCHEMA_VERSION = 1
SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True)
class PlayerSettings:
    """Ustawienia odtwarzacza (milisekundy)."""

    skip_ms: int = 3000
    auto_rewind_enabled: bool = True
    auto_rewind_ms: int = 1500
    segment_preroll_ms: int = 500
    # Podczas odtwarzania edytor przewija się do aktywnego segmentu.
    follow_playback: bool = True
    # Fala dźwiękowa rozwinięta pod suwakiem (zapamiętane zwinięcie).
    waveform_visible: bool = True


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
    """Czcionka edytora; wartości puste/zerowe oznaczają czcionkę domyślną.

    ``autocomplete`` włącza podpowiedzi wstawek i słów z dokumentu.
    """

    font_family: str = ""
    font_size_pt: int = 0
    autocomplete: bool = False


@dataclass(frozen=True)
class NotationSettings:
    """Konwencje zapisu notacji (wartości ``EllipsisStyle``)."""

    ellipsis_style: str = DEFAULT_ELLIPSIS_STYLE.value

    @property
    def ellipsis(self) -> EllipsisStyle:
        return EllipsisStyle(self.ellipsis_style)


@dataclass(frozen=True)
class ValidatorSettings:
    """Włączone reguły walidatora: JSON ``{kod: true/false}`` z nadpisaniami.

    Pusty napis oznacza zestaw domyślny; brak kodu w słowniku — wartość
    domyślną tej reguły (nowe reguły dostają ją automatycznie).
    """

    overrides_spec: str = ""

    @property
    def overrides(self) -> dict[str, bool]:
        decoded = decode_bool_map(self.overrides_spec)
        return decoded if decoded is not None else {}

    @property
    def enabled(self) -> frozenset[str]:
        return enabled_codes(self.overrides)


def decode_bool_map(raw: str) -> dict[str, bool] | None:
    """Słownik ``{tekst: bool}`` z JSON; pusty napis → pusty słownik."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, bool) for key, value in data.items()
    ):
        return None
    return data


def encode_bool_map(values: Mapping[str, bool]) -> str:
    """Zapis słownika ``{tekst: bool}``; pusty słownik → pusty napis."""
    return json.dumps(dict(sorted(values.items()))) if values else ""


@dataclass(frozen=True)
class ShortcutSettings:
    """Skróty różne od domyślnych: JSON ``{id akcji: [skróty]}``.

    Pusta lista oznacza akcję bez skrótu; brak akcji — skróty domyślne.
    Zapis skrótów jak w ``QKeySequence`` (np. ``Ctrl+Shift+A``).
    """

    overrides_spec: str = ""

    @property
    def overrides(self) -> dict[str, list[str]]:
        decoded = decode_shortcut_map(self.overrides_spec)
        return decoded if decoded is not None else {}


def decode_shortcut_map(raw: str) -> dict[str, list[str]] | None:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not all(
        isinstance(key, str)
        and isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        for key, value in data.items()
    ):
        return None
    return data


def encode_shortcut_map(values: Mapping[str, list[str]]) -> str:
    return json.dumps(dict(sorted(values.items()))) if values else ""


@dataclass(frozen=True)
class Snippet:
    """Wstawka: tekst w składni ``^x`` (indeks górny) i opcjonalny skrót."""

    text: str
    shortcut: str = ""


@dataclass(frozen=True)
class SnippetSettings:
    """Wstawki użytkownika: JSON listy ``{"text": …, "shortcut": …}``."""

    spec: str = ""

    @property
    def snippets(self) -> tuple[Snippet, ...]:
        decoded = decode_snippets(self.spec)
        return decoded if decoded is not None else ()


def decode_snippets(raw: str) -> tuple[Snippet, ...] | None:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    snippets: list[Snippet] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        text = item.get("text")
        shortcut = item.get("shortcut", "")
        if not isinstance(text, str) or not text or not isinstance(shortcut, str):
            return None
        snippets.append(Snippet(text, shortcut))
    return tuple(snippets)


def encode_snippets(snippets: Iterable[Snippet]) -> str:
    items = [
        {"text": snippet.text, "shortcut": snippet.shortcut}
        for snippet in snippets
        if snippet.text
    ]
    return json.dumps(items, ensure_ascii=False) if items else ""


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
class ExportSettings:
    """Eksport (faza 12): szablon DOCX i domyślne opcje „Eksportuj jako…”.

    ``template_path`` pusty = szablon wbudowany. ``last_format`` to klucz
    formatu z ``export/registry.py`` ostatnio wybrany w oknie eksportu.
    """

    template_path: str = ""
    superscript_mode: str = UNICODE
    untimed_mode: str = UNTIMED_INTERPOLATE
    last_format: str = "docx"


@dataclass(frozen=True)
class AsrSettings:
    """Model ASR, katalog modeli, urządzenie i globalny słownik.

    ``models_root`` pusty oznacza katalog domyślny w danych użytkownika;
    ``vocabulary`` to hasła rozdzielone znakami nowej linii.
    """

    model_key: str = DEFAULT_MODEL.key
    models_root: str = ""
    device: str = "auto"
    vocabulary: str = ""
    # Transkrypcja fragmentami: mniej pamięci RAM przy długich nagraniach.
    chunked: bool = False
    # Słowa z czasami i pewnością (faza 11): podkreślenie niepewnych słów
    # o pewności poniżej progu (w procentach; orientacyjny — faza 15).
    word_timestamps: bool = True
    # Podział szkicu na mówców (diaryzacja) — działa po pobraniu modelu.
    diarize: bool = True
    show_uncertain_words: bool = True
    word_threshold_pct: int = 40

    @property
    def word_threshold(self) -> float:
        return self.word_threshold_pct / 100

    @property
    def vocabulary_words(self) -> tuple[str, ...]:
        return split_vocabulary(self.vocabulary)


def split_vocabulary(text: str) -> tuple[str, ...]:
    """Hasła słownika ASR z tekstu: po jednym w linii, bez pustych."""
    return tuple(line.strip() for line in text.splitlines() if line.strip())


@dataclass(frozen=True)
class Settings:
    player: PlayerSettings = field(default_factory=PlayerSettings)
    editor: EditorSettings = field(default_factory=EditorSettings)
    notation: NotationSettings = field(default_factory=NotationSettings)
    validator: ValidatorSettings = field(default_factory=ValidatorSettings)
    shortcuts: ShortcutSettings = field(default_factory=ShortcutSettings)
    snippets: SnippetSettings = field(default_factory=SnippetSettings)
    project: ProjectSettings = field(default_factory=ProjectSettings)
    metadata: MetadataSettings = field(default_factory=MetadataSettings)
    export: ExportSettings = field(default_factory=ExportSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    asr: AsrSettings = field(default_factory=AsrSettings)


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
WORD_THRESHOLD_RANGE_PCT = (5, 95)
ELLIPSIS_STYLES = tuple(style.value for style in EllipsisStyle)
MODEL_KEYS = tuple(model.key for model in MODELS)

_FIELDS: tuple[_Field, ...] = (
    _Field("player", "skip_ms", int, *SKIP_RANGE_MS),
    _Field("player", "auto_rewind_enabled", bool),
    _Field("player", "auto_rewind_ms", int, *AUTO_REWIND_RANGE_MS),
    _Field("player", "segment_preroll_ms", int, *SEGMENT_PREROLL_RANGE_MS),
    _Field("player", "follow_playback", bool),
    _Field("player", "waveform_visible", bool),
    _Field("editor", "font_family", str),
    _Field("editor", "font_size_pt", int, *FONT_SIZE_RANGE_PT),
    _Field("editor", "autocomplete", bool),
    _Field("notation", "ellipsis_style", str, choices=ELLIPSIS_STYLES),
    _Field(
        "validator",
        "overrides_spec",
        str,
        validate=lambda raw: decode_bool_map(raw) is not None,
    ),
    _Field(
        "shortcuts",
        "overrides_spec",
        str,
        validate=lambda raw: decode_shortcut_map(raw) is not None,
    ),
    _Field(
        "snippets", "spec", str, validate=lambda raw: decode_snippets(raw) is not None
    ),
    _Field("project", "autosave_enabled", bool),
    _Field("project", "autosave_interval_s", int, *AUTOSAVE_INTERVAL_RANGE_S),
    _Field(
        "metadata",
        "fields_spec",
        str,
        validate=lambda raw: decode_fields(raw) is not None,
    ),
    _Field("export", "template_path", str),
    _Field("export", "superscript_mode", str, choices=SUPERSCRIPT_MODES),
    _Field("export", "untimed_mode", str, choices=UNTIMED_MODES),
    _Field("export", "last_format", str),
    _Field("appearance", "theme", str, choices=THEMES),
    _Field("appearance", "language", str, choices=LANGUAGE_CHOICES),
    _Field("asr", "model_key", str, choices=MODEL_KEYS),
    _Field("asr", "models_root", str),
    _Field("asr", "device", str, choices=DEVICES),
    _Field("asr", "vocabulary", str),
    _Field("asr", "chunked", bool),
    _Field("asr", "word_timestamps", bool),
    _Field("asr", "diarize", bool),
    _Field("asr", "show_uncertain_words", bool),
    _Field("asr", "word_threshold_pct", int, *WORD_THRESHOLD_RANGE_PCT),
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
        "validator": {},
        "shortcuts": {},
        "snippets": {},
        "project": {},
        "metadata": {},
        "export": {},
        "appearance": {},
        "asr": {},
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
        validator=replace(
            ValidatorSettings(), **sections["validator"]  # type: ignore[arg-type]
        ),
        shortcuts=replace(
            ShortcutSettings(), **sections["shortcuts"]  # type: ignore[arg-type]
        ),
        snippets=replace(
            SnippetSettings(), **sections["snippets"]  # type: ignore[arg-type]
        ),
        project=replace(
            ProjectSettings(), **sections["project"]  # type: ignore[arg-type]
        ),
        metadata=replace(
            MetadataSettings(), **sections["metadata"]  # type: ignore[arg-type]
        ),
        export=replace(
            ExportSettings(), **sections["export"]  # type: ignore[arg-type]
        ),
        appearance=replace(
            AppearanceSettings(), **sections["appearance"]  # type: ignore[arg-type]
        ),
        asr=replace(AsrSettings(), **sections["asr"]),  # type: ignore[arg-type]
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
