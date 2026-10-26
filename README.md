# Transkryptor

Lokalna aplikacja desktopowa do ręcznej transkrypcji fonetycznej języka
polskiego, wspomagana automatycznym szkicem ASR.

Strona projektu z opisem i pobieraniem najnowszej wersji:
<https://transkryptorapp.pl/>

## Wymagania deweloperskie

- Python 3.12 (runtime docelowy)
- [uv](https://docs.astral.sh/uv/) do zarządzania środowiskiem i zależnościami

## Rozpoczęcie pracy

```sh
uv sync                 # powtarzalne środowisko z uv.lock (pobierze Python 3.12, jeśli brak)
uv run transkryptor     # punkt wejścia aplikacji
uv run pytest           # testy jednostkowe i integracyjne
```

Testy end-to-end (`tests/e2e`) przechodzą całe ścieżki pracy w oknie
programu i porównują eksporty oraz zapis projektu z plikami wzorcowymi
(`tests/e2e/golden`). Zwykły `pytest` je pomija - w GitHub Actions biegną
tylko w workflow wydania, zamiast testów jednostkowych z CI:

```sh
uv run pytest --e2e tests/e2e                   # testy e2e
uv run pytest --e2e tests/e2e --update-golden   # po zamierzonej zmianie formatu
```

Po `--update-golden` przejrzyj różnicę wzorców w `git diff` i zacommituj ją
razem ze zmianą kodu.

Albo jednym skryptem (synchronizuje środowisko przy pierwszym uruchomieniu
i startuje aplikację):

```sh
./run.sh
```

Formatowanie i kontrole jakości kodu:

```sh
./check.sh              # tylko formatowanie (black)
./check.sh -l -m -t     # dodatkowo lint (ruff), typy (mypy) i testy (pytest)
./check.sh -e           # testy end-to-end
./check.sh --all        # to samo co -l -m -t -e
```

## Licencja

`GPL-3.0-or-later` - zobacz [LICENSE](LICENSE).

## User guide

PL: [Instrukcja użytkownika](docs/user_guide_pl.pdf)

EN: [User guide](docs/user_guide_en.pdf)
