# Transkryptor

Lokalna aplikacja desktopowa do ręcznej transkrypcji fonetycznej języka
polskiego, wspomagana automatycznym szkicem ASR.

## Wymagania deweloperskie

- Python 3.12 (runtime docelowy)
- [uv](https://docs.astral.sh/uv/) do zarządzania środowiskiem i zależnościami

## Rozpoczęcie pracy

```sh
uv sync                 # powtarzalne środowisko z uv.lock (pobierze Python 3.12, jeśli brak)
uv run transkryptor     # punkt wejścia aplikacji
uv run pytest           # testy jednostkowe i integracyjne
```

Albo jednym skryptem (synchronizuje środowisko przy pierwszym uruchomieniu
i startuje aplikację):

```sh
./run.sh
```

## Licencja

`GPL-3.0-or-later` — zobacz [LICENSE](LICENSE).

## User guide

PL: [Instrukcja użytkownika](docs/user_guide_pl.pdf)

EN: [User guide](docs/user_guide_en.pdf)
