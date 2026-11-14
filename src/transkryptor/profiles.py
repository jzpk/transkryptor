"""Profile notacji: nazwane zestawy ustawień zapisu (bez zależności od Qt).

Profil obejmuje reguły fonetyczne użytkownika (TOML), włączone reguły
walidatora, wstawki, autouzupełnianie, zapis wielokropka, szablon DOCX
i pola metryczki. Bieżące ustawienia (``Settings``) i plik reguł
użytkownika są roboczą kopią aktywnego profilu: :func:`capture` robi
z nich profil, a :func:`apply_profile` wpisuje profil z powrotem.

Profile leżą w katalogu danych programu (``paths.profiles_dir``), po
jednym pliku JSON na profil; :class:`ProfileLibrary` zapisuje je atomowo
(``fileio.write_atomic``). Ten sam format służy do eksportu i importu
profilu, żeby zespół mógł dzielić się jednym standardem zapisu.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from transkryptor.document.metadata import decode_fields
from transkryptor.errors import ProfileError
from transkryptor.fileio import write_atomic
from transkryptor.i18n import tr
from transkryptor.notation.ellipsis import DEFAULT_ELLIPSIS_STYLE, EllipsisStyle
from transkryptor.settings import (
    Settings,
    decode_bool_map,
    decode_snippets,
    encode_bool_map,
    encode_snippets,
)

logger = logging.getLogger(__name__)

PROFILE_FORMAT = "transkryptor-profile"
PROFILE_VERSION = 1
PROFILE_SUFFIX = ".json"
NAME_MAX_LENGTH = 80


@dataclass(frozen=True)
class NotationProfile:
    """Nazwany zestaw ustawień zapisu.

    Pola ``*_spec`` mają format odpowiednich pól ``Settings`` (pusty napis
    oznacza zestaw domyślny), ``rules_toml`` - format pliku reguł użytkownika.
    """

    name: str
    rules_toml: str = ""
    validator_spec: str = ""
    snippets_spec: str = ""
    autocomplete: bool = False
    ellipsis_style: str = DEFAULT_ELLIPSIS_STYLE.value
    template_path: str = ""
    metadata_fields_spec: str = ""

    def renamed(self, name: str) -> NotationProfile:
        return replace(self, name=name)


def capture(name: str, settings: Settings, rules_toml: str) -> NotationProfile:
    """Profil z bieżących ustawień i reguł użytkownika."""
    return NotationProfile(
        name=name,
        rules_toml=rules_toml,
        validator_spec=settings.validator.overrides_spec,
        snippets_spec=settings.snippets.spec,
        autocomplete=settings.editor.autocomplete,
        ellipsis_style=settings.notation.ellipsis_style,
        template_path=settings.export.template_path,
        metadata_fields_spec=settings.metadata.fields_spec,
    )


def apply_profile(profile: NotationProfile, settings: Settings) -> Settings:
    """Ustawienia z wartościami profilu i jego nazwą jako aktywnym profilem.

    Reguły fonetyczne (``rules_toml``) zapisuje wywołujący - leżą
    w osobnym pliku.
    """
    return replace(
        settings,
        validator=replace(settings.validator, overrides_spec=profile.validator_spec),
        snippets=replace(settings.snippets, spec=profile.snippets_spec),
        editor=replace(settings.editor, autocomplete=profile.autocomplete),
        notation=replace(settings.notation, ellipsis_style=profile.ellipsis_style),
        export=replace(settings.export, template_path=profile.template_path),
        metadata=replace(settings.metadata, fields_spec=profile.metadata_fields_spec),
        profiles=replace(settings.profiles, active=profile.name),
    )


def normalized_name(name: str) -> str:
    """Nazwa profilu bez zbędnych odstępów, przycięta do ``NAME_MAX_LENGTH``."""
    return " ".join(name.split())[:NAME_MAX_LENGTH]


def unique_name(name: str, taken: set[str] | list[str] | tuple[str, ...]) -> str:
    """``name`` albo ``name (2)``, ``name (3)``… - pierwsza wolna nazwa."""
    base = normalized_name(name) or tr("profiles.default_name")
    if base not in taken:
        return base
    number = 2
    while f"{base} ({number})" in taken:
        number += 1
    return f"{base} ({number})"


# --- format pliku ----------------------------------------------------------


def dumps_profile(profile: NotationProfile) -> str:
    """Profil jako czytelny JSON (pliki biblioteki i eksport)."""
    data = {
        "format": PROFILE_FORMAT,
        "version": PROFILE_VERSION,
        "name": profile.name,
        "rules": profile.rules_toml,
        "validator": decode_bool_map(profile.validator_spec) or {},
        "snippets": json.loads(profile.snippets_spec) if profile.snippets_spec else [],
        "autocomplete": profile.autocomplete,
        "ellipsis_style": profile.ellipsis_style,
        "docx_template": profile.template_path,
        "metadata_fields": (
            json.loads(profile.metadata_fields_spec)
            if profile.metadata_fields_spec
            else None
        ),
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def loads_profile(raw: str, source: str) -> NotationProfile:
    """Profil z JSON; uszkodzony plik → ``ProfileError`` (``source`` w opisie)."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise _invalid(source) from exc
    if not isinstance(data, dict) or data.get("format") != PROFILE_FORMAT:
        raise _invalid(source)
    version = data.get("version")
    if not isinstance(version, int) or version > PROFILE_VERSION:
        raise ProfileError(
            tr("profiles.error.newer", name=source),
            tr("profiles.error.newer.hint"),
        )
    try:
        return _parse(data)
    except (TypeError, ValueError) as exc:
        raise _invalid(source) from exc


def _parse(data: dict[str, Any]) -> NotationProfile:
    name = normalized_name(_text(data.get("name")))
    if not name:
        raise ValueError("profile name")
    validator = data.get("validator", {})
    validator_spec = encode_bool_map(validator) if isinstance(validator, dict) else ""
    if decode_bool_map(validator_spec) is None:
        raise ValueError("validator")
    snippets_spec = _json_spec(data.get("snippets", []))
    snippets = decode_snippets(snippets_spec)
    if snippets is None:
        raise ValueError("snippets")
    fields = data.get("metadata_fields")
    fields_spec = "" if fields is None else _json_spec(fields)
    if decode_fields(fields_spec) is None:
        raise ValueError("metadata fields")
    ellipsis = _text(data.get("ellipsis_style", DEFAULT_ELLIPSIS_STYLE.value))
    if ellipsis not in {style.value for style in EllipsisStyle}:
        raise ValueError("ellipsis style")
    autocomplete = data.get("autocomplete", False)
    if not isinstance(autocomplete, bool):
        raise ValueError("autocomplete")
    return NotationProfile(
        name=name,
        rules_toml=_text(data.get("rules", "")),
        validator_spec=validator_spec,
        snippets_spec=encode_snippets(snippets),
        autocomplete=autocomplete,
        ellipsis_style=ellipsis,
        template_path=_text(data.get("docx_template", "")),
        metadata_fields_spec=fields_spec,
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected text")
    return value


def _json_spec(value: object) -> str:
    """Lista z pliku profilu w zapisie ustawień (pusta lista → pusty napis)."""
    if not isinstance(value, list):
        raise TypeError("expected list")
    return json.dumps(value, ensure_ascii=False) if value else ""


def _invalid(source: str) -> ProfileError:
    return ProfileError(
        tr("profiles.error.invalid", name=source), tr("profiles.error.invalid.hint")
    )


def read_profile(path: Path) -> NotationProfile:
    """Profil z pliku (np. importowanego); błąd odczytu → ``ProfileError``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProfileError(
            tr("profiles.error.read", name=path.name, reason=exc),
            tr("profiles.error.read.hint"),
        ) from exc
    return loads_profile(raw, path.name)


def write_profile(profile: NotationProfile, path: Path) -> None:
    """Zapis atomowy profilu (biblioteka i eksport); błąd → ``ProjectError``."""
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, dumps_profile(profile).encode("utf-8"))


# --- biblioteka profili ----------------------------------------------------


def sort_key(name: str) -> tuple[str, str]:
    """Klucz sortowania nazw: bez wielkości liter i znaków diakrytycznych."""
    folded = name.casefold()
    base = "".join(
        char
        for char in unicodedata.normalize("NFKD", folded.replace("ł", "l"))
        if not unicodedata.combining(char)
    )
    return base, folded


_UNSAFE_FILE_CHARS = re.compile(r"[^\w-]+", re.UNICODE)


def _file_stem(name: str) -> str:
    stem = _UNSAFE_FILE_CHARS.sub("-", name.casefold()).strip("-_")
    return stem[:40] or "profile"


class ProfileLibrary:
    """Profile zapisane w katalogu, rozpoznawane po nazwie z pliku.

    Uszkodzone pliki są pomijane (z wpisem w dzienniku) - nie blokują pracy.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _files(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        try:
            paths = sorted(self.directory.glob(f"*{PROFILE_SUFFIX}"))
        except OSError:
            return found
        for path in paths:
            try:
                profile = read_profile(path)
            except ProfileError:
                logger.warning("Skipping invalid profile file %s", path.name)
                continue
            found.setdefault(profile.name, path)
        return found

    def names(self) -> list[str]:
        """Nazwy profili w kolejności alfabetycznej."""
        return sorted(self._files(), key=sort_key)

    def load(self, name: str) -> NotationProfile | None:
        path = self._files().get(name)
        if path is None:
            return None
        try:
            return read_profile(path)
        except ProfileError:
            return None

    def save(self, profile: NotationProfile) -> None:
        """Zapisuje profil (nadpisuje profil o tej samej nazwie)."""
        files = self._files()
        path = files.get(profile.name) or self._new_path(
            profile.name, set(files.values())
        )
        write_profile(profile, path)

    def delete(self, name: str) -> None:
        path = self._files().get(name)
        if path is not None:
            path.unlink(missing_ok=True)

    def rename(self, old: str, new: str) -> NotationProfile | None:
        """Zmienia nazwę profilu; None, gdy profilu nie ma."""
        files = self._files()
        path = files.get(old)
        profile = self.load(old)
        if path is None or profile is None:
            return None
        renamed = profile.renamed(new)
        write_profile(renamed, path)
        return renamed

    def _new_path(self, name: str, taken: set[Path]) -> Path:
        stem = _file_stem(name)
        candidate = self.directory / f"{stem}{PROFILE_SUFFIX}"
        number = 2
        while candidate in taken or candidate.exists():
            candidate = self.directory / f"{stem}-{number}{PROFILE_SUFFIX}"
            number += 1
        return candidate
