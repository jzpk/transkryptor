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
pod bezpiecznymi nazwami (bez katalogów i nazw zarezerwowanych w Windows),
więc paczka nie zapisze niczego poza wskazanym katalogiem. Elementy
archiwum są czytane z limitem rozmiaru (bomba ZIP nie wyczerpie pamięci),
a pliki trafiają najpierw do katalogu tymczasowego obok celu
(:func:`stage_pack`) - pod docelowe nazwy przenosi je dopiero
:meth:`StagedPack.commit` po zgodzie użytkownika. Nagranie musi mieć sumę
SHA-256 z manifestu, zgodną z sumą w projekcie z paczki. Zapis paczki przechodzi przez ``fileio.atomic_output``.
Scalanie ustawień z paczki z własnymi jest w ``document/pack_settings.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from transkryptor import __version__
from transkryptor.document.pack_checks import (
    audio_mismatch,
    check_project_audio,
    check_unique_names,
    checked_name,
    invalid_pack,
    safe_name,
)
from transkryptor.document.project import PROJECT_SUFFIX, ProjectState, dumps
from transkryptor.errors import ProjectError
from transkryptor.fileio import (
    SizeLimitError,
    atomic_output,
    file_sha256,
    limited_chunks,
    read_limited,
)
from transkryptor.i18n import tr

PACK_SUFFIX = ".tkpack"
PACK_FORMAT = "transkryptor-pack"
PACK_VERSION = 1
MANIFEST = "manifest.json"
# Powyżej tego rozmiaru nagrania okno eksportu ostrzega o dużej paczce.
LARGE_AUDIO_BYTES = 500 * 1024 * 1024
_COPY_CHUNK = 1 << 20
# Limity rozmiaru elementów archiwum po rozpakowaniu. Nagranie musi się
# zgadzać z rozmiarem z nagłówka ZIP i zmieścić w MAX_AUDIO_BYTES oraz
# w wolnym miejscu na dysku (z zapasem DISK_MARGIN_BYTES).
MAX_AUDIO_BYTES = 16 * 1024**3
DISK_MARGIN_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SETTINGS_BYTES = 16 * 1024 * 1024
MAX_PROJECT_BYTES = 256 * 1024 * 1024
MAX_TEMPLATE_BYTES = 64 * 1024 * 1024
_STAGING_PREFIX = ".tkpack-"
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


@dataclass(frozen=True)
class StagedPack:
    """Paczka rozpakowana do katalogu tymczasowego ``staging`` obok celu.

    Nic jeszcze nie leży pod docelowymi nazwami w ``directory`` - użytkownik
    może zobaczyć zawartość i zrezygnować bez śladu na dysku.
    """

    manifest: PackManifest
    settings: PackSettings
    directory: Path
    staging: Path

    @property
    def has_template(self) -> bool:
        return bool(self.manifest.template)

    def commit(self) -> OpenedPack:
        """Przenosi pliki pod docelowe nazwy (nadpisuje istniejące)."""
        manifest = self.manifest
        try:
            project = self._move(manifest.project)
            audio = self._move(manifest.audio_name) if manifest.audio_included else None
            template = self._move(manifest.template) if manifest.template else None
        except OSError as exc:
            raise ProjectError(
                user_message=tr(
                    "project.error.save",
                    name=manifest.project,
                    reason=exc.strerror or exc,
                ),
                retry_hint=tr("project.error.save.hint"),
            ) from exc
        return OpenedPack(manifest, project, audio, self.settings, template)

    def _move(self, name: str) -> Path:
        target = self.directory / name
        (self.staging / name).replace(target)
        return target


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
    source = _with_audio_sha(source, audio)
    template = source.template_path if _is_file(source.template_path) else None
    template_name = safe_name(template.name) if template is not None else ""
    manifest: dict[str, Any] = {
        "format": PACK_FORMAT,
        "version": PACK_VERSION,
        "app_version": __version__,
        "created": datetime.now().replace(microsecond=0).isoformat(),
        "project": _project_name(source.project_name),
        "audio": _audio_manifest(source, audio),
        "template": template_name,
    }
    with (
        atomic_output(target) as handle,
        zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False))
        archive.writestr(f"project/{manifest['project']}", _project_json(source))
        if audio is not None:
            # Nazwa jak w manifeście (bezpieczna), bo po niej szuka odczyt.
            # Nagrania (MP3, AAC…) są już skompresowane.
            audio_name = (manifest["audio"] or {}).get("name") or safe_name(audio.name)
            archive.write(
                audio, f"audio/{audio_name}", compress_type=zipfile.ZIP_STORED
            )
        _write_settings(archive, source.settings)
        if template is not None:
            archive.write(template, f"settings/{template_name}")


def read_manifest(path: Path) -> PackManifest:
    """Manifest paczki; plik, który nie jest paczką → ``ProjectError``."""
    try:
        with zipfile.ZipFile(path) as archive:
            return _manifest(archive)
    except (OSError, zipfile.BadZipFile, ValueError, KeyError, TypeError) as exc:
        raise invalid_pack(path) from exc


def conflicts(manifest: PackManifest, directory: Path) -> list[str]:
    """Pliki paczki, które już istnieją w ``directory`` (zostałyby nadpisane)."""
    return [name for name in _extracted_names(manifest) if (directory / name).exists()]


@contextlib.contextmanager
def stage_pack(path: Path, directory: Path) -> Iterator[StagedPack]:
    """Rozpakowuje paczkę do katalogu tymczasowego w ``directory``.

    Pliki trafiają pod docelowe nazwy dopiero po :meth:`StagedPack.commit`;
    wyjście z bloku ``with`` usuwa katalog tymczasowy, więc anulowany import
    nie zostawia plików. Błąd → ``ProjectError``.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=directory))
    except OSError as exc:
        raise ProjectError(
            user_message=tr(
                "project.error.save", name=directory.name, reason=exc.strerror or exc
            ),
            retry_hint=tr("project.error.save.hint"),
        ) from exc
    try:
        yield _unpack(path, directory, staging)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _unpack(path: Path, directory: Path, staging: Path) -> StagedPack:
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _manifest(archive)
            _extract(archive, f"project/{manifest.project}", staging, MAX_PROJECT_BYTES)
            check_project_audio(staging / manifest.project, manifest.audio_sha256, path)
            if manifest.audio_included:
                member = f"audio/{manifest.audio_name}"
                _check_audio_entry(archive.getinfo(member), staging, path)
                digest = _extract(archive, member, staging)
                if digest != manifest.audio_sha256.lower():
                    raise audio_mismatch(path)
            if manifest.template:
                _extract(
                    archive,
                    f"settings/{manifest.template}",
                    staging,
                    MAX_TEMPLATE_BYTES,
                )
            settings = _read_settings(archive)
    except ProjectError:
        raise
    except (OSError, zipfile.BadZipFile, ValueError, KeyError, TypeError) as exc:
        raise invalid_pack(path) from exc
    return StagedPack(manifest, settings, directory, staging)


# --- zapis -------------------------------------------------------------------


def _with_audio_sha(source: PackSource, audio: Path | None) -> PackSource:
    """Źródło z sumą nagrania w projekcie - paczka z nagraniem musi ją mieć.

    Suma bywa jeszcze pusta, gdy program liczy ją w tle (``HashThread``);
    wtedy liczy ją zapis paczki.
    """
    ref = source.state.audio
    if audio is None or ref is None or ref.sha256:
        return source
    state = replace(source.state, audio=replace(ref, sha256=file_sha256(audio)))
    return replace(source, state=state)


def _audio(source: PackSource) -> Path | None:
    if not source.include_audio or not _is_file(source.audio_path):
        return None
    return source.audio_path


def _is_file(path: Path | None) -> bool:
    return path is not None and path.is_file()


def _project_name(name: str) -> str:
    stem = safe_name(Path(name).stem) or "projekt"
    return f"{stem}{PROJECT_SUFFIX}"


# Ostatnio zserializowany projekt: (stan, JSON). Okno eksportu liczy rozmiar
# paczki przy każdej zmianie opcji, a zapis paczki potrzebuje tego samego
# JSON-a - projekt (do 256 MB) jest serializowany raz. Stan jest niezmienny
# (frozen; słowniki w nim po ``capture_state`` nikt nie zmienia), więc ten sam
# obiekt oznacza tę samą treść.
_last_project_json: tuple[ProjectState, str] | None = None


def _project_json(source: PackSource) -> str:
    """Projekt z nagraniem wskazanym względnie - obok pliku projektu."""
    global _last_project_json
    state = source.state
    if _last_project_json is not None and _last_project_json[0] is state:
        return _last_project_json[1]
    packed = state
    if state.audio is not None:
        audio = replace(state.audio, relative_path=safe_name(state.audio.name))
        packed = replace(state, audio=audio)
    text = dumps(packed)
    _last_project_json = (state, text)
    return text


def _audio_manifest(source: PackSource, audio: Path | None) -> dict[str, Any] | None:
    ref = source.state.audio
    if ref is None:
        return None
    return {
        "name": safe_name(ref.name),
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


def _check_audio_entry(info: zipfile.ZipInfo, staging: Path, path: Path) -> None:
    """Nagranie musi być zapisane bez kompresji (tak zapisuje ``write_pack``),
    nie większe niż ``MAX_AUDIO_BYTES`` i mieścić się na dysku.

    Rozmiar z nagłówka ZIP podaje autor paczki - spreparowana paczka
    zapełniłaby dysk w katalogu docelowym, zanim odczyt wykryje oszustwo.
    """
    if info.compress_type != zipfile.ZIP_STORED:
        raise ValueError("nagranie w paczce musi być zapisane bez kompresji")
    if info.file_size > MAX_AUDIO_BYTES:
        raise SizeLimitError(MAX_AUDIO_BYTES)
    if info.file_size + DISK_MARGIN_BYTES > shutil.disk_usage(staging).free:
        raise ProjectError(
            user_message=tr(
                "pack.error.no_space",
                name=path.name,
                size=math.ceil(info.file_size / (1024 * 1024)),
            ),
            retry_hint=tr("pack.error.no_space.hint"),
        )


def _manifest(archive: zipfile.ZipFile) -> PackManifest:
    data = json.loads(_read_member(archive, MANIFEST, MAX_MANIFEST_BYTES))
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
    project = checked_name(data["project"])
    if not project.endswith(PROJECT_SUFFIX):
        raise ValueError("nieprawidłowa nazwa projektu")
    audio = data.get("audio")
    audio = audio if isinstance(audio, dict) else {}
    template = data.get("template") or ""
    manifest = PackManifest(
        version=version,
        project=project,
        audio_name=checked_name(audio["name"]) if audio else "",
        audio_sha256=str(audio.get("sha256", "")),
        audio_included=bool(audio.get("included", False)),
        template=checked_name(template) if template else "",
        created=str(data.get("created", "")),
        app_version=str(data.get("app_version", "")),
    )
    if manifest.audio_included and not _SHA256.fullmatch(manifest.audio_sha256.lower()):
        raise ValueError("nagranie w paczce bez sumy SHA-256")
    check_unique_names(_extracted_names(manifest))
    return manifest


def _extracted_names(manifest: PackManifest) -> list[str]:
    """Nazwy plików, które paczka zapisuje w katalogu docelowym."""
    names = [manifest.project]
    if manifest.audio_included:
        names.append(manifest.audio_name)
    if manifest.template:
        names.append(manifest.template)
    return names


def _read_settings(archive: zipfile.ZipFile) -> PackSettings:
    names = set(archive.namelist())

    def text(name: str) -> str:
        member = f"settings/{name}"
        if member not in names:
            return ""
        return _read_member(archive, member, MAX_SETTINGS_BYTES).decode("utf-8")

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


def _read_member(archive: zipfile.ZipFile, member: str, limit: int) -> bytes:
    """Element archiwum w pamięci; większy niż ``limit`` → ``SizeLimitError``.

    Rozmiar z nagłówka odrzuca dużą paczkę od razu, a odczyt z limitem
    chroni przed nagłówkiem, który zaniża rozmiar.
    """
    info = archive.getinfo(member)
    if info.file_size > limit:
        raise SizeLimitError(limit)
    with archive.open(info) as source:
        return read_limited(source, limit)


def _extract(
    archive: zipfile.ZipFile, member: str, directory: Path, limit: int | None = None
) -> str:
    """Rozpakowuje element do ``directory`` pod jego nazwą; zwraca SHA-256.

    Bez ``limit`` obowiązuje rozmiar z nagłówka ZIP.
    """
    info = archive.getinfo(member)
    limit = info.file_size if limit is None else limit
    if info.file_size > limit:
        raise SizeLimitError(limit)
    digest = hashlib.sha256()
    target = directory / PurePosixPath(member).name
    with archive.open(info) as source, target.open("wb") as handle:
        chunks = iter(lambda: source.read(_COPY_CHUNK), b"")
        for chunk in limited_chunks(chunks, limit):
            handle.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()
