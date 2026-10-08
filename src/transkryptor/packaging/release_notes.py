"""Noty wydania: co jest w paczce, jak to sprawdzić i czego się spodziewać.

Nota jest jedynym dokumentem, który trafia do użytkownika razem z plikami,
więc musi zawierać komplet wymagany przez ``specs/phases/05-release.md``:
sumy kontrolne, zasady prywatności, instrukcję pobrania modelu, wymagania
sprzętowe i znane ograniczenia ASR. Treść powstaje z tych samych stałych,
z których korzystają instalator i dokumentacja (``packaging.metadata``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as date_type
from pathlib import Path

from transkryptor.asr.models import DEFAULT_MODEL, format_size
from transkryptor.packaging.checksums import CHECKSUM_FILE, Checksum
from transkryptor.packaging.metadata import (
    APP_NAME,
    BENCHMARK_MACHINE,
    HARDWARE_REQUIREMENTS,
    LICENSE_ID,
    PUBLISHER,
    REALTIME_FACTOR,
    VERSION,
    targets,
)

RELEASE_NOTES_FILE = "RELEASE-NOTES.md"

# Ograniczenia, o których użytkownik musi wiedzieć przed pierwszym użyciem.
# Pochodzą z ryzyk planu implementacji i z zakresu MVP w specs/requirements.md.
KNOWN_LIMITATIONS = (
    "Szkic ASR jest hipotezą **ortograficzną**, a nie zapisem fonetycznym "
    "według notacji projektu. Każdy fragment wymaga korekty transkrybenta.",
    "Jakość rozpoznawania nie została zmierzona na zatwierdzonym korpusie "
    "referencyjnym — projekt takiego korpusu nie posiada. Podane czasy "
    "dotyczą wydajności, nie trafności.",
    "Model nie rozpoznaje nosowości, labializacji, dyftongizacji ani "
    "redukcji „ł”; propozycje zapisu fonetycznego są regułowe i zawsze "
    "wymagają decyzji użytkownika.",
    "MVP przyjmuje nagrania MP3, WAV, FLAC, M4A, AAC, OGG, OPUS i WMA "
    "oraz eksportuje wyłącznie DOCX.",
    "MVP nie zapisuje projektu ani sesji roboczej: po zamknięciu aplikacji "
    "praca istnieje tylko w wyeksportowanym pliku DOCX. Aplikacja ostrzega "
    "przed zamknięciem z niewyeksportowanymi zmianami.",
    "Transkrypcja działa na CPU. Czas rośnie w przybliżeniu proporcjonalnie "
    "do spadku liczby rdzeni.",
)

# Zmiany widoczne dla użytkownika w bieżącej wersji (faza 06 i 07).
WHATS_NEW = (
    "Okno **Ustawienia…** (`Ctrl+,`): skok i auto-cofanie odtwarzacza, "
    "cofnięcie przed segmentem ASR, czcionka edytora i styl wielokropka.",
    "Sterowanie odtwarzaczem z klawiatury przy fokusie w edytorze: "
    "odtwórz/pauza `Ctrl+Spacja` lub `F4`, skok `Alt+←/→`, tempo "
    "`Ctrl+Shift+,`/`.`; pętla A–B `Ctrl+Shift+A/B/L` i auto-cofanie "
    "przy wznowieniu po pauzie.",
    "Kliknięcie segmentu szkicu ASR odtwarza nagranie od jego początku.",
    "Wyszukiwanie i zamiana (`Ctrl+F`, `Ctrl+H`, `F3`/`Shift+F3`) z opcjami "
    "wielkości liter, całych słów i wyrażeń regularnych; w zamienniku `^n` "
    "nadaje literze indeks górny (np. `be^ndzie`), a „Zamień wszystkie” to "
    "jedno cofnięcie.",
    "Domyślny zapis pauzy i urwanego słowa to teraz `…` (jeden znak); "
    "`...` można wybrać w ustawieniach. Walidator rozumie oba zapisy. "
    "**Dokumenty pisane w starszych wersjach** (z `...`) zostaną oznaczone "
    "wskazówką VAL-05 — przycisk „Ujednolić wielokropki” nad listą "
    "ostrzeżeń zamienia je wszystkie jednym krokiem cofania.",
)

PRIVACY_POINTS = (
    "Aplikacja nie zbiera telemetrii i niczego nie raportuje.",
    "Nagranie i tekst nie opuszczają komputera — nie ma ASR w chmurze "
    "ani synchronizacji.",
    "Pobranie modelu ASR jest jednorazowe i uruchamiane wyłącznie po jawnej "
    "zgodzie użytkownika.",
    "Przy starcie aplikacja sprawdza w GitHub Releases, czy jest nowa wersja "
    "(najwyżej 2 zapytania na dobę, bez identyfikatora instalacji i bez "
    "danych użytkownika), i pobiera ją w tle; instalacja następuje po "
    "kliknięciu „Uruchom ponownie i zaktualizuj”.",
    "Po pobraniu modelu transkrypcja działa bez dostępu do Internetu.",
    "Aplikacja nie prowadzi historii dokumentów: dane istnieją w pamięci "
    "bieżącej sesji i są utrwalane tylko przez eksport DOCX.",
    "Ustawienia (odtwarzacz, czcionka edytora, styl wielokropka) są "
    "zapisywane lokalnie "
    "(Linux: `~/.config/transkryptor`, Windows: rejestr "
    "`HKCU\\Software\\transkryptor`) i nie zawierają tekstu ani ścieżek nagrań.",
)


def _artifact_table(checksums: Iterable[Checksum], version: str) -> list[str]:
    """Tabela artefaktów z platformą, rozmiarem i sumą kontrolną."""
    platform_by_name = {
        target.artifact_name: target.display_name
        for target in targets(version).values()
    }
    lines = [
        "| Plik | Platforma | Rozmiar | SHA-256 |",
        "| --- | --- | --- | --- |",
    ]
    for entry in checksums:
        platform = platform_by_name.get(entry.name, "—")
        size = f"{entry.size_bytes / 1_000_000:.0f} MB"
        lines.append(f"| `{entry.name}` | {platform} | {size} | `{entry.digest}` |")
    return lines


def render_release_notes(
    checksums: Iterable[Checksum],
    *,
    version: str = VERSION,
    release_date: date_type | None = None,
    source_url: str | None = None,
) -> str:
    """Składa treść pliku ``RELEASE-NOTES.md`` dla podanego zestawu plików."""
    model = DEFAULT_MODEL
    when = release_date or date_type.today()
    entries = tuple(checksums)
    available = targets(version)

    lines = [
        f"# {APP_NAME} {version}",
        "",
        f"Data wydania: {when.isoformat()}  ",
        f"Licencja: `{LICENSE_ID}`",
        "",
        f"{APP_NAME} to lokalna aplikacja do ręcznej transkrypcji fonetycznej",
        "języka polskiego, wspomagana opcjonalnym szkicem ASR działającym",
        "na komputerze użytkownika.",
        "",
        "## Nowości w tej wersji",
        "",
        *(f"- {item}" for item in WHATS_NEW),
        "",
        "## Artefakty",
        "",
    ]
    lines += _artifact_table(entries, version)
    names = {entry.name for entry in entries}
    lines += [
        "",
        "Sumy kontrolne wszystkich plików są też w `" + CHECKSUM_FILE + "`.",
        "Sprawdzenie po pobraniu:",
        "",
        "```sh",
        f"sha256sum --check {CHECKSUM_FILE}",
        "```",
        "",
        *(
            [
                "W PowerShell:",
                "",
                "```powershell",
                f"Get-FileHash .\\{available['windows'].artifact_name} "
                "-Algorithm SHA256",
                "```",
                "",
            ]
            if available["windows"].artifact_name in names
            else []
        ),
        "## Instalacja",
        "",
        f"- **Windows** — uruchom `{available['windows'].artifact_name}`.",
        f"  Wymagany {available['windows'].baseline}. Instalator zawiera komplet",
        "  środowiska uruchomieniowego: **Python nie musi być zainstalowany**.",
        "- **Linux** — nadaj prawo wykonywania plikowi",
        f"  `{available['linux'].artifact_name}` (`chmod +x`) i uruchom go.",
        f"  Zbudowano na: {available['linux'].baseline}.",
        "",
        "Po pierwszym uruchomieniu aplikacja jest w pełni sprawna do pracy",
        "ręcznej — model ASR nie jest do tego potrzebny.",
        "",
        "## Prywatność",
        "",
    ]
    lines += [f"- {point}" for point in PRIVACY_POINTS]
    lines += [
        "",
        "## Model ASR: pobranie i praca offline",
        "",
        f"- Model: **{model.display_name}**",
        f"- Źródło: <{model.source_url}>",
        f"- Licencja modelu: `{model.license_id}`",
        f"- Rozmiar pobrania: **{format_size(model.approx_size_bytes)}**",
        "",
        "Kroki:",
        "",
        "1. Otwórz panel „Szkic ASR” w oknie aplikacji.",
        "2. Panel pokazuje nazwę modelu, jego licencję, rozmiar i katalog",
        "   docelowy. Pobieranie rusza dopiero po potwierdzeniu.",
        "3. Postęp widać w panelu; pobieranie można anulować, a po błędzie",
        "   ponowić. Przerwane pobranie nigdy nie jest uznawane za gotowy model.",
        "4. Po pobraniu transkrypcja działa lokalnie — również z odłączoną siecią.",
        "",
        "Katalog modelu:",
        "",
        "- Windows: `%APPDATA%\\Transkryptor\\models`",
        "- Linux: `~/.local/share/transkryptor/models`",
        "",
        "Model można usunąć w dowolnej chwili — aplikacja wróci do pracy ręcznej.",
        "",
        "## Wymagania sprzętowe",
        "",
        "| Zasób | Minimum | Zalecane | Podstawa |",
        "| --- | --- | --- | --- |",
    ]
    for requirement in HARDWARE_REQUIREMENTS:
        lines.append(
            f"| {requirement.resource} | {requirement.minimum} | "
            f"{requirement.recommended} | {requirement.basis} |"
        )
    lines += [
        "",
        "Zmierzony stosunek czasu transkrypcji do długości nagrania:",
        f"**{REALTIME_FACTOR}** na maszynie referencyjnej ({BENCHMARK_MACHINE})",
        "— godzinne nagranie to około pół godziny pracy procesora. Pełny raport",
        "pomiarów i opis maszyny: `docs/benchmarks-asr.md` w repozytorium projektu.",
        "",
        "## Znane ograniczenia",
        "",
    ]
    lines += [f"- {limitation}" for limitation in KNOWN_LIMITATIONS]
    lines += [
        "",
        "## Licencje",
        "",
        f"Aplikacja: `{LICENSE_ID}` — pełny tekst w pliku `LICENSE` wewnątrz",
        "artefaktu. Licencje wszystkich zależności i bibliotek natywnych:",
        "`licenses/THIRD-PARTY-NOTICES.md`. Nota o modelu ASR (nie jest",
        "redystrybuowany razem z aplikacją): `licenses/MODEL-LICENSE.md`.",
        "",
        "Artefakt zawiera biblioteki na licencjach GPL i LGPL w postaci",
        "binarnej. Qt jest w nim osobnymi bibliotekami dynamicznymi, więc",
        "użytkownik może je podmienić na własną zgodną wersję.",
        "",
        "### Kod źródłowy",
        "",
    ]
    if source_url:
        lines.append(f"Kod źródłowy tego wydania: <{source_url}>")
    else:
        lines.append(
            f"Kod źródłowy tego wydania udostępnia {PUBLISHER} na warunkach "
            f"`{LICENSE_ID}`."
        )
    lines += [
        "",
        "Źródła bibliotek natywnych na licencjach GPL i LGPL wskazuje tabela",
        "w `licenses/THIRD-PARTY-NOTICES.md`.",
        "",
    ]
    return "\n".join(lines)


def write_release_notes(
    checksums: Iterable[Checksum],
    dest_dir: Path,
    *,
    version: str = VERSION,
    release_date: date_type | None = None,
    source_url: str | None = None,
) -> Path:
    """Zapisuje noty wydania obok artefaktów i zwraca ścieżkę pliku."""
    target = dest_dir / RELEASE_NOTES_FILE
    target.write_text(
        render_release_notes(
            checksums,
            version=version,
            release_date=release_date,
            source_url=source_url,
        ),
        encoding="utf-8",
    )
    return target


__all__ = [
    "KNOWN_LIMITATIONS",
    "PRIVACY_POINTS",
    "RELEASE_NOTES_FILE",
    "render_release_notes",
    "write_release_notes",
]
