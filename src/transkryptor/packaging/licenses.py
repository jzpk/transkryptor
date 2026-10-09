"""Zbieranie licencji aplikacji, zależności i bibliotek natywnych.

Wymaganie wydania z ``specs/acceptance.md``: „licencje aplikacji, zależności
i modelu są dołączone do artefaktu wydania”. Moduł buduje katalog
``licenses/`` wkładany do artefaktu: tekst licencji aplikacji, teksty licencji
każdej zależności runtime odczytane z metadanych zainstalowanych pakietów,
noty bibliotek natywnych dołączanych w kołach PyPI oraz notę o modelu ASR,
który nie jest redystrybuowany.

Rejestr zależności i uzasadnienie zgodności z GPL-3.0-or-later prowadzi
``docs/licenses.md``; ten moduł zbiera teksty, a nie podejmuje decyzji
licencyjnych.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path, PurePath

from transkryptor.asr.models import DEFAULT_MODEL, format_size
from transkryptor.packaging.metadata import (
    APP_NAME,
    ASSETS_DIR,
    LICENSE_ID,
    PUBLISHER,
    REPO_ROOT,
)

# Teksty licencji dołączane przez wydawcę dla kół, które ich nie zawierają.
# Pochodzenie każdego pliku opisuje assets/licenses/README.md.
VENDORED_LICENSES = ASSETS_DIR / "licenses"

# Dopasowanie identyfikatora licencji z metadanych do kanonicznego tekstu.
# Kolejność ma znaczenie: „LGPL” musi wygrać z „GPL”, a „Apache 2.0” (zapis
# bez SPDX) z samym „Apache”.
SPDX_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("lgpl-3", "LGPL-3.0"),
    ("lesser general public license", "LGPL-3.0"),
    ("apache", "Apache-2.0"),
)

# Bezpośrednie zależności runtime z ``pyproject.toml``. Pozostałe pakiety
# dochodzą przez domknięcie ``Requires-Dist``; grupy deweloperskie
# (pytest, pyinstaller) nie trafiają do artefaktu i nie są tu wymieniane.
DIRECT_RUNTIME_DISTRIBUTIONS = (
    "PySide6",
    "python-docx",
    "faster-whisper",
    "av",
    "huggingface-hub",
    "httpx",
    "regex",
)

# Pliki licencji w katalogu ``*.dist-info`` pakietu.
LICENSE_FILE_PATTERN = re.compile(
    r"(licen[cs]e|licence|copying|notice|authors|patents)", re.IGNORECASE
)

# Nazwa zależności w ``Requires-Dist`` kończy się przed znakiem wersji,
# nawiasem kwadratowym (extra) lub średnikiem (marker środowiska).
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9._-]+)")


@dataclass(frozen=True)
class NativeLibraryNote:
    """Nota o bibliotece natywnej dołączonej w kole PyPI, nie w źródłach."""

    component: str
    shipped_by: str
    license_id: str
    source_url: str
    note: str


# Odpowiedź na otwarte ryzyka zapisane w docs/licenses.md do fazy 05.
#
# PyAV: koło ``av`` dołącza własny zestaw bibliotek FFmpeg w katalogu
# ``av.libs``. Obecność ``libx264`` i ``libx265`` dowodzi, że ten FFmpeg jest
# zbudowany z ``--enable-gpl``, więc całość rozprowadzamy jako
# GPL-2.0-or-later — zgodnie z licencją aplikacji (GPL-3.0-or-later).
# Wymusza to dołączenie tekstów licencji oraz wskazania źródeł tych bibliotek.
#
# Qt: PyInstaller pakuje Qt jako osobne biblioteki dynamiczne (tryb onedir),
# więc użytkownik może je podmienić — to warunek zgodności z LGPL-3.0.
NATIVE_LIBRARY_NOTES: tuple[NativeLibraryNote, ...] = (
    NativeLibraryNote(
        component="Qt 6 (biblioteki dynamiczne wraz z PySide6)",
        shipped_by="PySide6",
        license_id="LGPL-3.0-only",
        source_url="https://download.qt.io/official_releases/QtForPython/",
        note=(
            "Artefakt zawiera Qt jako osobne biblioteki dynamiczne "
            "(.so/.dll) obok programu, nie jako jeden scalony plik "
            "wykonywalny. Użytkownik może je podmienić na własną zgodną "
            "wersję: w AppImage po rozpakowaniu "
            "(--appimage-extract), w instalacji Windows bezpośrednio "
            "w katalogu programu."
        ),
    ),
    NativeLibraryNote(
        component="FFmpeg dołączony do koła PyAV (katalog av.libs)",
        shipped_by="av (PyAV)",
        license_id="GPL-2.0-or-later",
        source_url="https://ffmpeg.org/releases/",
        note=(
            "Zestaw zawiera kodery libx264 i libx265 na licencji "
            "GPL-2.0-or-later, więc dołączony FFmpeg jest zbudowany "
            "z opcją --enable-gpl i cały artefakt rozprowadzamy na "
            "warunkach GPL. Aplikacja używa wyłącznie dekodowania "
            "nagrania dla silnika ASR."
        ),
    ),
    NativeLibraryNote(
        component="libx264",
        shipped_by="av (PyAV)",
        license_id="GPL-2.0-or-later",
        source_url="https://code.videolan.org/videolan/x264",
        note="Koder wideo dołączony do FFmpeg w kole PyAV; nieużywany przez aplikację.",
    ),
    NativeLibraryNote(
        component="libx265",
        shipped_by="av (PyAV)",
        license_id="GPL-2.0-or-later",
        source_url="https://bitbucket.org/multicoreware/x265_git",
        note="Koder wideo dołączony do FFmpeg w kole PyAV; nieużywany przez aplikację.",
    ),
    NativeLibraryNote(
        component="libmp3lame",
        shipped_by="av (PyAV)",
        license_id="LGPL-2.0-or-later",
        source_url="https://lame.sourceforge.io/",
        note="Koder MP3 dołączony do FFmpeg w kole PyAV.",
    ),
    NativeLibraryNote(
        component="GnuTLS, Nettle, libgmp",
        shipped_by="av (PyAV)",
        license_id="LGPL-2.1-or-later",
        source_url="https://www.gnutls.org/download.html",
        note="Warstwa TLS dołączonego FFmpeg; aplikacja nie zestawia z niej połączeń.",
    ),
    NativeLibraryNote(
        component="FFmpeg dołączony do Qt Multimedia",
        shipped_by="PySide6",
        license_id="LGPL-2.1-or-later",
        source_url="https://ffmpeg.org/releases/",
        note=(
            "Backend odtwarzania nagrań w Qt Multimedia; wersja i nota "
            "zgłaszane przy starcie aplikacji."
        ),
    ),
    NativeLibraryNote(
        component="libctranslate2, libgomp",
        shipped_by="ctranslate2",
        license_id="MIT (libctranslate2), GPL-3.0-or-later WITH "
        "GCC-exception-3.1 (libgomp)",
        source_url="https://github.com/OpenNMT/CTranslate2",
        note=(
            "Inferencja modelu Whisper na CPU. libgomp (OpenMP z GCC) ma "
            "wyjątek runtime, który nie nakłada dodatkowych warunków."
        ),
    ),
)


@dataclass(frozen=True)
class DistributionLicense:
    """Licencja jednej zależności runtime wraz z dołączonymi plikami."""

    name: str
    version: str
    license_id: str
    files: tuple[str, ...] = field(default_factory=tuple)
    from_wheel: bool = True

    @property
    def has_text(self) -> bool:
        """Czy udało się dołączyć pełny tekst licencji, a nie tylko jej nazwę."""
        return bool(self.files)


@dataclass(frozen=True)
class LicenseBundle:
    """Wynik zebrania licencji: katalog docelowy i co się w nim znalazło."""

    root: Path
    notices: Path
    distributions: tuple[DistributionLicense, ...]

    def without_text(self) -> tuple[DistributionLicense, ...]:
        """Zależności, dla których koło nie zawiera pliku z tekstem licencji."""
        return tuple(dist for dist in self.distributions if not dist.has_text)


def _requirement_name(requirement: str) -> str | None:
    """Nazwa pakietu z wpisu ``Requires-Dist`` (bez wersji i extras)."""
    match = _REQUIREMENT_NAME.match(requirement)
    return match.group(1) if match else None


def _is_optional(requirement: str) -> bool:
    """Czy wpis ``Requires-Dist`` dotyczy wyłącznie opcjonalnego extra."""
    _, _, marker = requirement.partition(";")
    return "extra ==" in marker


def runtime_distributions(
    direct: tuple[str, ...] = DIRECT_RUNTIME_DISTRIBUTIONS,
) -> list[importlib_metadata.Distribution]:
    """Domknięcie zależności runtime zainstalowanych w środowisku.

    Przechodzi ``Requires-Dist`` wszerz, pomijając wpisy dostępne tylko przez
    extras. Pakiety nieobecne w środowisku są pomijane: koło mogło ich nie
    potrzebować na tej platformie (np. zależności warunkowe).
    """
    seen: dict[str, importlib_metadata.Distribution] = {}
    queue = list(direct)
    while queue:
        name = queue.pop(0)
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = importlib_metadata.distribution(name)
        except importlib_metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        for requirement in dist.requires or ():
            if _is_optional(requirement):
                continue
            dependency = _requirement_name(requirement)
            if dependency:
                queue.append(dependency)
    return [seen[key] for key in sorted(seen)]


def license_id_of(dist: importlib_metadata.Distribution) -> str:
    """Identyfikator licencji z metadanych pakietu.

    Kolejność źródeł odpowiada praktyce ekosystemu: wyrażenie SPDX
    (``License-Expression``), pole ``License``, a na końcu klasyfikatory.
    """
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    declared = meta.get("License")
    if declared and "\n" not in declared.strip() and len(declared.strip()) < 100:
        return declared.strip()
    classifiers = [
        value.split("::")[-1].strip()
        for value in meta.get_all("Classifier") or ()
        if value.startswith("License ::")
    ]
    if classifiers:
        return ", ".join(classifiers)
    return "nieokreślona w metadanych"


def _looks_like_license(entry: PurePath) -> bool:
    """Czy ścieżka w kole wygląda na plik z tekstem licencji."""
    tail = entry.parts[-1]
    if tail.endswith((".py", ".pyc", ".json", ".so", ".pyd", ".dll")):
        return False
    in_licenses_dir = any(part == "licenses" for part in entry.parts)
    return in_licenses_dir or bool(LICENSE_FILE_PATTERN.search(tail))


def _license_files(dist: importlib_metadata.Distribution) -> list[Path]:
    """Pliki z tekstem licencji dołączone do koła pakietu.

    Szuka w katalogu metadanych (``*.dist-info``) oraz — bo część kół trzyma
    licencję przy kodzie, np. ``onnxruntime/LICENSE`` — na pierwszych dwóch
    poziomach samego pakietu.
    """
    found: list[Path] = []
    for entry in dist.files or ():
        in_metadata = any(
            part.endswith((".dist-info", ".egg-info")) for part in entry.parts
        )
        shallow = len(entry.parts) <= 2
        if not (in_metadata or shallow) or not _looks_like_license(entry):
            continue
        resolved = Path(str(dist.locate_file(entry)))
        if resolved.is_file():
            found.append(resolved)
    return sorted(set(found))


def vendored_license_files(name: str, license_id: str) -> list[Path]:
    """Teksty licencji dołączane przez wydawcę, gdy koło ich nie zawiera.

    Najpierw plik przypisany wprost do pakietu, potem kanoniczny tekst SPDX
    dopasowany do identyfikatora licencji z metadanych.
    """
    per_package = VENDORED_LICENSES / "packages" / name.lower().replace("_", "-")
    if per_package.is_dir():
        return sorted(path for path in per_package.iterdir() if path.is_file())
    needle = license_id.lower()
    for marker, spdx in SPDX_FALLBACKS:
        if marker in needle:
            canonical = VENDORED_LICENSES / "spdx" / f"{spdx}.txt"
            if canonical.is_file():
                return [canonical]
    return []


def collect_distribution_licenses(
    dest: Path,
    distributions: list[importlib_metadata.Distribution] | None = None,
) -> tuple[DistributionLicense, ...]:
    """Kopiuje teksty licencji zależności do ``dest`` i opisuje, co zebrano."""
    dists = distributions if distributions is not None else runtime_distributions()
    collected: list[DistributionLicense] = []
    for dist in dists:
        name = dist.metadata["Name"] or "nieznany"
        version = dist.version
        license_id = license_id_of(dist)
        sources = _license_files(dist)
        from_wheel = bool(sources)
        if not sources:
            sources = vendored_license_files(name, license_id)
        target_dir = dest / f"{name}-{version}"
        copied: list[str] = []
        for source in sources:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / source.name
            shutil.copyfile(source, target)
            copied.append(f"{target_dir.name}/{target.name}")
        collected.append(
            DistributionLicense(
                name=name,
                version=version,
                license_id=license_id,
                files=tuple(sorted(copied)),
                from_wheel=from_wheel,
            )
        )
    return tuple(collected)


def render_notices(distributions: tuple[DistributionLicense, ...]) -> str:
    """Treść pliku ``THIRD-PARTY-NOTICES.md`` dołączanego do artefaktu."""
    lines = [
        "# Licencje zależności i bibliotek natywnych",
        "",
        f"{APP_NAME} jest rozpowszechniany na warunkach `{LICENSE_ID}`; pełny",
        "tekst licencji aplikacji znajduje się w pliku `LICENSE` obok tego pliku.",
        "Artefakt zawiera też oprogramowanie osób trzecich wymienione poniżej.",
        "Pełne teksty licencji leżą w katalogu `third-party/`.",
        "",
        "## Zależności Pythona",
        "",
        "| Zależność | Wersja | Licencja | Tekst licencji | Pochodzenie tekstu |",
        "| --- | --- | --- | --- | --- |",
    ]
    for dist in distributions:
        files = (
            "<br>".join(f"`{path}`" for path in dist.files)
            if dist.files
            else "**brak tekstu — do uzupełnienia przed wydaniem**"
        )
        if not dist.files:
            origin = "—"
        elif dist.from_wheel:
            origin = "koło PyPI"
        else:
            origin = "tekst kanoniczny dołączony przez wydawcę"
        lines.append(
            f"| {dist.name} | {dist.version} | {dist.license_id} | {files} | "
            f"{origin} |"
        )
    lines += [
        "",
        "## Biblioteki natywne dołączone w kołach PyPI",
        "",
        "Poniższe biblioteki nie są zależnościami Pythona: trafiają do artefaktu",
        "jako pliki binarne wewnątrz kół `PySide6`, `av` i `ctranslate2`.",
        "",
        "| Komponent | Dostarczone przez | Licencja | Źródło |",
        "| --- | --- | --- | --- |",
    ]
    for note in NATIVE_LIBRARY_NOTES:
        lines.append(
            f"| {note.component} | {note.shipped_by} | {note.license_id} | "
            f"<{note.source_url}> |"
        )
    lines += ["", "### Uwagi", ""]
    for note in NATIVE_LIBRARY_NOTES:
        lines.append(f"- **{note.component}** — {note.note}")
    lines += [
        "",
        "## Kod źródłowy komponentów GPL i LGPL",
        "",
        "Artefakt zawiera biblioteki na licencjach GPL i LGPL w postaci binarnej.",
        "Odpowiadający im kod źródłowy jest dostępny pod adresami wskazanymi",
        "w kolumnie „Źródło”, w wersjach wymienionych w tabelach powyżej.",
        f"Kod źródłowy samej aplikacji dostarcza {PUBLISHER} na tych samych",
        "warunkach co artefakt — patrz noty wydania.",
        "",
    ]
    return "\n".join(lines)


def render_model_notice() -> str:
    """Treść pliku ``MODEL-LICENSE.md``: model nie jest redystrybuowany."""
    model = DEFAULT_MODEL
    return "\n".join(
        [
            "# Model rozpoznawania mowy",
            "",
            f"- Model: **{model.display_name}**",
            f"- Repozytorium: <{model.source_url}>",
            f"- Licencja modelu: `{model.license_id}`",
            f"- Rozmiar pobrania: {format_size(model.approx_size_bytes)}",
            "",
            "Wagi modelu **nie są częścią tego artefaktu**. Aplikacja pobiera je",
            "ze wskazanego repozytorium dopiero po jawnej zgodzie użytkownika,",
            "do katalogu danych użytkownika. Bez modelu aplikacja uruchamia się",
            "i pozwala transkrybować ręcznie.",
            "",
            "Po pobraniu transkrypcja działa lokalnie i nie wymaga dostępu do sieci.",
            "",
        ]
    )


def write_license_bundle(
    dest: Path,
    *,
    app_license: Path | None = None,
    distributions: list[importlib_metadata.Distribution] | None = None,
) -> LicenseBundle:
    """Tworzy komplet licencji w ``dest`` i zwraca opis zebranej zawartości."""
    dest.mkdir(parents=True, exist_ok=True)
    source_license = app_license or (REPO_ROOT / "LICENSE")
    if not source_license.is_file():
        raise FileNotFoundError(f"Nie znaleziono licencji aplikacji: {source_license}")
    shutil.copyfile(source_license, dest / "LICENSE")
    collected = collect_distribution_licenses(
        dest / "third-party", distributions=distributions
    )
    notices = dest / "THIRD-PARTY-NOTICES.md"
    notices.write_text(render_notices(collected), encoding="utf-8")
    (dest / "MODEL-LICENSE.md").write_text(render_model_notice(), encoding="utf-8")
    return LicenseBundle(root=dest, notices=notices, distributions=collected)


__all__ = [
    "DistributionLicense",
    "LicenseBundle",
    "NATIVE_LIBRARY_NOTES",
    "NativeLibraryNote",
    "collect_distribution_licenses",
    "license_id_of",
    "render_model_notice",
    "render_notices",
    "runtime_distributions",
    "vendored_license_files",
    "write_license_bundle",
]
