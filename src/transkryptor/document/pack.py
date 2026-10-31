"""Paczka do przekazania pracy (``.tkpack``): projekt z nagraniem i ustawieniami.

Paczka to archiwum ZIP z plikiem ``manifest.json`` (format i numer wersji
``PACK_VERSION``, żeby dało się go później rozszerzać) oraz:

- ``project/<nazwa>.transkr`` - projekt; ścieżka względna nagrania to sama
  nazwa pliku, więc po rozpakowaniu projekt znajduje nagranie obok siebie;
- ``audio/<nazwa>`` - nagranie (opcjonalnie; bez niego projekt wiąże
  nagranie po sumie SHA-256 zapisanej w manifeście i w projekcie);
- ``settings/rules.toml`` - reguły fonetyczne użytkownika;
- ``settings/snippets.json`` - wstawki;
- ``settings/notation.json`` - zapis wielokropka i reguły walidatora;
- ``settings/<nazwa>.docx`` - szablon DOCX użyty w projekcie.

Rozpakowanie bierze z archiwum tylko pliki wymienione w manifeście,
pod bezpiecznymi nazwami (bez katalogów), więc paczka nie zapisze niczego
poza wskazanym katalogiem. Zapis przechodzi przez ``fileio.atomic_output``.
Scalanie ustawień z paczki z własnymi jest w ``document/pack_settings.py``.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from transkryptor import __version__
from transkryptor.document.project import PROJECT_SUFFIX, ProjectState, dumps
from transkryptor.errors import ProjectError
from transkryptor.fileio import atomic_output
from transkryptor.i18n import tr

PACK_SUFFIX = ".tkpack"
PACK_FORMAT = "transkryptor-pack"
PACK_VERSION = 1
MANIFEST = "manifest.json"
# Powyżej tego rozmiaru nagrania okno eksportu ostrzega o dużej paczce.
LARGE_AUDIO_BYTES = 500 * 1024 * 1024
_COPY_CHUNK = 1 << 20


def file_dialog_filter() -> str:
    return tr("pack.file_filter", pattern=f"*{PACK_SUFFIX}")


@dataclass(frozen=True)
class PackSettings:
    """Ustawienia notacji przekazywane w paczce (puste - pominięte)."""

    rules_toml: str = ""
    snippets_spec: str = ""
    ellipsis_style: str = ""
    validator_spec: str = ""

    @property
    def has_notation(self) -> bool:
        return bool(self.ellipsis_style or self.validator_spec)


@dataclass(frozen=True)
class PackSource:
    """Co trafia do paczki."""

    state: ProjectState
    project_name: str
    audio_path: Path | None = None
    include_audio: bool = True
    settings: PackSettings = PackSettings()
    template_path: Path | None = None


@dataclass(frozen=True)
class PackManifest:
    version: int
    project: str
    audio_name: str = ""
    audio_sha256: str = ""
    audio_included: bool = False
    template: str = ""
    created: str = ""
    app_version: str = ""


@dataclass(frozen=True)
class OpenedPack:
    """Rozpakowana paczka: pliki w katalogu docelowym i ustawienia."""

    manifest: PackManifest
    project_path: Path
    audio_path: Path | None
    settings: PackSettings
    template_path: Path | None


def estimated_size(source: PackSource) -> int:
    """Przybliżony rozmiar paczki w bajtach (nagranie się nie kompresuje)."""
    size = len(_project_json(source).encode("utf-8"))
    for path in (_audio(source), source.template_path):
        if path is not None:
            try:
                size += path.stat().st_size
            except OSError:
                continue
    return size


def audio_size(source: PackSource) -> int:
    path = _audio(source)
    try:
        return path.stat().st_size if path is not None else 0
    except OSError:
        return 0


def write_pack(target: Path, source: PackSource) -> None:
    """Zapisuje paczkę atomowo; błąd zapisu → ``ProjectError``."""
    audio = _audio(source)
    template = source.template_path if _is_file(source.template_path) else None
    manifest: dict[str, Any] = {
        "format": PACK_FORMAT,
        "version": PACK_VERSION,
        "app_version": __version__,
        "created": datetime.now().replace(microsecond=0).isoformat(),
        "project": _project_name(source.project_name),
        "audio": _audio_manifest(source, audio),
        "template": template.name if template is not None else "",
    }
    with (
        atomic_output(target) as handle,
        zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False))
        archive.writestr(f"project/{manifest['project']}", _project_json(source))
        if audio is not None:
            # Nagrania (MP3, AAC…) są już skompresowane.
            archive.write(
                audio, f"audio/{audio.name}", compress_type=zipfile.ZIP_STORED
            )
        _write_settings(archive, source.settings)
        if template is not None:
            archive.write(template, f"settings/{template.name}")


def read_manifest(path: Path) -> PackManifest:
    """Manifest paczki; plik, który nie jest paczką → ``ProjectError``."""
    try:
        with zipfile.ZipFile(path) as archive:
            return _manifest(archive)
    except (OSError, zipfile.BadZipFile, ValueError, KeyError, TypeError) as exc:
        raise _invalid(path) from exc


def conflicts(manifest: PackManifest, directory: Path) -> list[str]:
    """Pliki paczki, które już istnieją w ``directory`` (zostałyby nadpisane)."""
    names = [manifest.project]
    if manifest.audio_included:
        names.append(manifest.audio_name)
    if manifest.template:
        names.append(manifest.template)
    return [name for name in names if (directory / name).exists()]


def open_pack(path: Path, directory: Path) -> OpenedPack:
    """Rozpakowuje paczkę do ``directory``; błąd → ``ProjectError``."""
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _manifest(archive)
            directory.mkdir(parents=True, exist_ok=True)
            project = _extract(
                archive, f"project/{manifest.project}", directory / manifest.project
            )
            audio = None
            if manifest.audio_included:
                audio = _extract(
                    archive,
                    f"audio/{manifest.audio_name}",
                    directory / manifest.audio_name,
                )
            template = None
            if manifest.template:
                template = _extract(
                    archive,
                    f"settings/{manifest.template}",
                    directory / manifest.template,
                )
            settings = _read_settings(archive)
    except ProjectError:
        raise
    except (OSError, zipfile.BadZipFile, ValueError, KeyError, TypeError) as exc:
        raise _invalid(path) from exc
    return OpenedPack(manifest, project, audio, settings, template)


# --- zapis -------------------------------------------------------------------


def _audio(source: PackSource) -> Path | None:
    if not source.include_audio or not _is_file(source.audio_path):
        return None
    return source.audio_path


def _is_file(path: Path | None) -> bool:
    return path is not None and path.is_file()


def _project_name(name: str) -> str:
    stem = _safe_name(Path(name).stem) or "projekt"
    return f"{stem}{PROJECT_SUFFIX}"


def _project_json(source: PackSource) -> str:
    """Projekt z nagraniem wskazanym względnie - obok pliku projektu."""
    state = source.state
    if state.audio is not None:
        audio = replace(state.audio, relative_path=_safe_name(state.audio.name))
        state = replace(state, audio=audio)
    return dumps(state)


def _audio_manifest(source: PackSource, audio: Path | None) -> dict[str, Any] | None:
    ref = source.state.audio
    if ref is None:
        return None
    return {
        "name": _safe_name(ref.name),
        "sha256": ref.sha256,
        "included": audio is not None,
    }


def _write_settings(archive: zipfile.ZipFile, settings: PackSettings) -> None:
    if settings.rules_toml:
        archive.writestr("settings/rules.toml", settings.rules_toml)
    if settings.snippets_spec:
        archive.writestr("settings/snippets.json", settings.snippets_spec)
    if settings.has_notation:
        archive.writestr(
            "settings/notation.json",
            json.dumps(
                {
                    "ellipsis_style": settings.ellipsis_style,
                    "validator": settings.validator_spec,
                },
                ensure_ascii=False,
            ),
        )


# --- odczyt ------------------------------------------------------------------


def _manifest(archive: zipfile.ZipFile) -> PackManifest:
    data = json.loads(archive.read(MANIFEST).decode("utf-8"))
    if not isinstance(data, dict) or data.get("format") != PACK_FORMAT:
        raise ValueError("to nie jest paczka Transkryptora")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("nieprawidłowa wersja paczki")
    if version > PACK_VERSION:
        raise ProjectError(
            user_message=tr(
                "pack.error.newer", version=version, supported=PACK_VERSION
            ),
            retry_hint=tr("pack.error.newer.hint"),
        )
    project = _checked_name(data["project"])
    if not project.endswith(PROJECT_SUFFIX):
        raise ValueError("nieprawidłowa nazwa projektu")
    audio = data.get("audio")
    audio = audio if isinstance(audio, dict) else {}
    template = data.get("template") or ""
    return PackManifest(
        version=version,
        project=project,
        audio_name=_checked_name(audio["name"]) if audio else "",
        audio_sha256=str(audio.get("sha256", "")),
        audio_included=bool(audio.get("included", False)),
        template=_checked_name(template) if template else "",
        created=str(data.get("created", "")),
        app_version=str(data.get("app_version", "")),
    )


def _read_settings(archive: zipfile.ZipFile) -> PackSettings:
    names = set(archive.namelist())

    def text(name: str) -> str:
        member = f"settings/{name}"
        return archive.read(member).decode("utf-8") if member in names else ""

    notation_raw = text("notation.json")
    notation = json.loads(notation_raw) if notation_raw else {}
    if not isinstance(notation, dict):
        raise ValueError("nieprawidłowe ustawienia notacji")
    return PackSettings(
        rules_toml=text("rules.toml"),
        snippets_spec=text("snippets.json"),
        ellipsis_style=str(notation.get("ellipsis_style", "")),
        validator_spec=str(notation.get("validator", "")),
    )


def _extract(archive: zipfile.ZipFile, member: str, target: Path) -> Path:
    with archive.open(member) as source, atomic_output(target) as handle:
        shutil.copyfileobj(source, handle, _COPY_CHUNK)
    return target


def _safe_name(name: str) -> str:
    """Sama nazwa pliku, bez katalogów i znaków niedozwolonych w Windows."""
    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = "".join("_" if ch in '<>:"|?*' or ord(ch) < 32 else ch for ch in base)
    return cleaned.strip(" .")


def _checked_name(value: Any) -> str:
    if not isinstance(value, str) or not value or _safe_name(value) != value:
        raise ValueError("nieprawidłowa nazwa pliku w paczce")
    return value


def _invalid(path: Path) -> ProjectError:
    return ProjectError(
        user_message=tr("pack.error.invalid", name=path.name),
        retry_hint=tr("pack.error.invalid.hint"),
    )
