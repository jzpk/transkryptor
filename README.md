# Transkryptor

Lokalna aplikacja desktopowa (Windows, Linux) do ręcznej transkrypcji
fonetycznej języka polskiego, wspomagana automatycznym szkicem ASR.
Nagrania i transkrypcje nie opuszczają komputera.

Strona projektu z opisem i pobieraniem najnowszej wersji:
<https://transkryptorapp.pl/>

## Najważniejsze funkcje

- Edytor transkrypcji z notacją fonetyczną, walidatorem zapisu, wstawkami
  i autouzupełnianiem oraz odtwarzacz nagrania z kotwicami czasu.
- Szkic ASR (faster-whisper) z podziałem na mówców (sherpa-onnx) i trybem
  recenzji szkicu.
- Profile notacji - nazwane zestawy reguł, szablonu DOCX i pól metryczki,
  do eksportu i importu w zespole.
- Projekty `.transkr`, paczki `.tkpack` oraz eksport do DOCX, ODT, PDF,
  TXT, ELAN (EAF), Praat (TextGrid) i napisów SRT/WebVTT.
- Pola tematyczne i części mowy (Morfeusz 2 ze słownikiem SGJP).
- Interfejs po polsku i angielsku, automatyczne aktualizacje z podpisanych
  wydań na GitHubie.

## Dokumentacja dla użytkowników

Program prowadzi po swoich funkcjach w **Samouczkach** - przycisk
„Samouczki” na dole okna albo zakładka „Samouczki” w ustawieniach. Opis
zmian w kolejnych wersjach jest w [CHANGELOG.md](CHANGELOG.md) i w oknie
„Co nowego” w programie.

## Wymagania deweloperskie

- Python 3.12 (runtime docelowy)
- [uv](https://docs.astral.sh/uv/) do zarządzania środowiskiem i zależnościami

## Rozpoczęcie pracy

```sh
uv sync                     # powtarzalne środowisko z uv.lock (pobierze Python 3.12, jeśli brak)
uv run transkryptor         # uruchomienie aplikacji
uv run transkryptor --self-test   # kompletność środowiska bez otwierania okna
```

Albo jednym skryptem (synchronizuje środowisko przy pierwszym uruchomieniu
i startuje aplikację):

```sh
./run.sh
```

## Testy

```sh
uv run pytest                                   # testy jednostkowe i integracyjne
uv run pytest --e2e tests/e2e                   # testy end-to-end
uv run pytest --e2e tests/e2e --update-golden   # po zamierzonej zmianie formatu
```

Testy end-to-end (`tests/e2e`) przechodzą całe ścieżki pracy w oknie
programu i porównują eksporty oraz zapis projektu z plikami wzorcowymi
(`tests/e2e/golden`). Zwykły `pytest` je pomija - w GitHub Actions biegną
tylko w workflow wydania. Po `--update-golden` przejrzyj różnicę wzorców
w `git diff` i zacommituj ją razem ze zmianą kodu.

Testy nie dotykają konfiguracji ani danych dewelopera - `tests/conftest.py`
kieruje katalogi użytkownika i `QSettings` do katalogu tymczasowego.

## Jakość kodu

```sh
./check.sh              # tylko formatowanie (black)
./check.sh -l -m -t     # dodatkowo lint (ruff), typy (mypy) i testy (pytest)
./check.sh -e           # testy end-to-end
./check.sh --all        # to samo co -l -m -t -e
uvx pre-commit install  # ruff, black i mypy przed każdym commitem
```

CI (`.github/workflows/ci.yml`) sprawdza przy każdym pushu na `main`
i `release/**` oraz w PR: ruff, black, mypy, testy i audyt zależności.

## Struktura repozytorium

| Ścieżka | Zawartość |
| --- | --- |
| `src/transkryptor/ui` | interfejs Qt (PySide6): okno, kontrolery, ustawienia, samouczki |
| `src/transkryptor/document` | model dokumentu, mówcy, metryczka, pola tematyczne, zapis projektu i paczek |
| `src/transkryptor/notation` | reguły notacji fonetycznej i walidator |
| `src/transkryptor/asr`, `audio` | szkic ASR, diaryzacja, nagranie |
| `src/transkryptor/export` | formaty eksportu (rejestr w `export/registry.py`) i import DOCX |
| `src/transkryptor/corpus` | praca na wielu projektach: katalog nagrań, wyszukiwanie, słownik form |
| `src/transkryptor/update` | samoaktualizacja i weryfikacja podpisu wydań |
| `src/transkryptor/packaging` | narzędzie wydania: budowanie artefaktów, sumy, noty, changelog |
| `src/transkryptor/i18n/locales` | tłumaczenia (`pl.json`, `en.json`) |
| `tests` | testy; `tests/e2e` - testy end-to-end z plikami wzorcowymi |
| `packaging` | spec PyInstallera i obrazy Docker do budowania artefaktów |
| `changelog.d` | fragmenty historii zmian do następnego wydania |

Warstwy domenowe (`asr`, `corpus`, `document`, `notation`, `update`,
`settings`, `fileio`) nie importują Qt ani `transkryptor.ui` - pilnuje tego
`tests/test_layers.py`. Zasady projektowe dla zmian w kodzie są
w [CLAUDE.md](CLAUDE.md).

## Historia zmian

Każda zmiana widoczna dla użytkownika dodaje fragment w `changelog.d/`
(zasady w [changelog.d/README.md](changelog.d/README.md)). `CHANGELOG.md`
zmienia tylko workflow wydania, który składa fragmenty w sekcję nowej
wersji.

## Gałęzie i scalanie

- `main` - rozwój następnej wersji minor/major.
- `release/X.Y` - poprawki wydanej serii (wydania patch). Scala się je
  tylko w przód, do `main`: `./merge-forward.sh X.Y`.
- `./integrate.sh [main|release/X.Y]` - scalenie gałęzi z worktree
  (rebase, lint, typy, testy, fast-forward celu pod blokadą); przy
  `release/X.Y` od razu scala ją też do `main`.

## Wydania

Wydanie robi workflow „Wydanie” (`.github/workflows/release.yml`):
Actions → „Wydanie” → Run workflow, z wyborem gałęzi i części wersji
(`patch` z `release/X.Y`, `minor`/`major` z `main`). Po zielonych testach
end-to-end workflow podbija wersję, składa changelog, nadaje tag `vX.Y.Z`,
buduje natywnie AppImage (Ubuntu 22.04) i instalator Windows (Inno Setup),
podpisuje sumy kontrolne (minisign) i publikuje GitHub Release, a na koniec
uruchamia przebudowę strony projektu.

Ostrzeżenie o wersjach z lukami bezpieczeństwa publikuje workflow
„Ostrzeżenie bezpieczeństwa” (`.github/workflows/advisory.yml`): Actions →
Run workflow z najniższą bezpieczną wersją i opisem luki. Podpisany plik
`advisory.json` trafia do wydania `advisory` (pre-release), a programy
w starszych wersjach pokazują ostrzeżenie z propozycją aktualizacji
(`src/transkryptor/update/advisory.py`). Odwołanie ostrzeżenia to nowe
ostrzeżenie z wersją `0.0.0`.

Artefakt dla bieżącej platformy można zbudować lokalnie:

```sh
uv sync --group packaging
uv run --group packaging python -m transkryptor.packaging --help
```

## Strona projektu i zgłoszenia

Strona `transkryptorapp.pl` i formularz zgłoszeń mają osobne repozytorium.
Zgłoszenia błędów i propozycje (także dotyczące strony) trafiają do
GitHub Issues tego repozytorium.

## Licencja

`GPL-3.0-or-later` - zobacz [LICENSE](LICENSE).
