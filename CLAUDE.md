# Instrukcje dla Claude

## Styl tekstu: zawsze „-” zamiast pauzy i półpauzy

W każdym tekście, który piszesz - kodzie, komentarzach, docstringach,
tłumaczeniach (`i18n/locales/*.json`), `CHANGELOG.md`, stronie (`pages/`),
dokumentacji, opisach commitów i PR - używaj zwykłego łącznika `-`
(U+002D). Nigdy nie wstawiaj pauzy (U+2014) ani półpauzy (U+2013),
także w zakresach (`A-B`, `0.0-1.0`).

Wyjątek: kod, który musi **rozpoznawać** te znaki w danych wejściowych
(np. import DOCX z wersji do 0.6.0 albo poprawionych przez Worda). Tam
zapisuj je kodami `\u2013` / `\u2014` i nie zamieniaj ich na `-` - np.
`_LEGEND_ITEM_RE` w `document/speakers.py`. Przy masowej zamianie pauz
na łączniki sprawdzaj najpierw regexy i parsery, żeby nie zepsuć importu
starszych plików.

## Na koniec każdego zadania zmieniającego kod

Wykonaj kolejno, zanim zgłosisz, że praca jest skończona:

1. **Lint i formatowanie:** `uv run ruff check .` oraz `uv run black --check .`
   (przy błędach formatowania uruchom `uv run black .`).
2. **Typy:** `uv run mypy`.
3. **Testy:** `uv run pytest -q`. Wszystkie muszą przechodzić; jeśli coś
   nie przechodzi, napraw to albo jasno zgłoś, co i dlaczego.
4. **Changelog:** dopisz zmiany widoczne dla użytkownika w sekcji
   `## Nieopublikowane` w `CHANGELOG.md` (po polsku, w stylu
   istniejących wpisów). Zmiany wyłącznie wewnętrzne (testy, CI,
   refaktoryzacja, instrukcje) nie trafiają do changeloga.
5. **Commit:** utwórz lokalny commit. Opis commita **po angielsku**, w trybie
   rozkazującym, z prefiksem typu zmiany (Conventional Commits):
   - `feat:` - nowa funkcja widoczna dla użytkownika,
   - `fix:` - poprawka błędu,
   - `deps:` - zmiana zależności (`pyproject.toml`, `uv.lock`),
   - `docs:` - dokumentacja,
   - `test:` - tylko testy,
   - `refactor:` - zmiana kodu bez zmiany zachowania,
   - `ci:` - workflowy GitHub Actions,
   - `build:` - pakowanie i budowanie wydań,
   - `chore:` - pozostałe prace porządkowe.

   Przykład: `fix: keep toolbar buttons reachable in narrow windows`.
6. **Scalenie (tylko tryb równoległy, patrz niżej):** uruchom
   `./integrate.sh` i doprowadź do kodu wyjścia 0.

**Nigdy nie wykonuj `git push`.** Wysyłkę na remote robi użytkownik.

## Tryb pracy: jeden agent albo kilku równolegle

Na początku zadania ustal tryb poleceniem `git rev-parse --show-toplevel`:

- **Tryb jednego agenta** - jesteś w głównym katalogu repozytorium na
  gałęzi `main`. Commitujesz bezpośrednio na `main`; krok 6 pomijasz.
- **Tryb równoległy** - jesteś w worktree pod `.claude/worktrees/<nazwa>`
  na własnej gałęzi. Równolegle mogą pracować inni agenci, każdy w swoim
  worktree. Obowiązują wtedy zasady poniżej.

### Zasady trybu równoległego

- Pracuj i commituj wyłącznie w swoim worktree, na swojej gałęzi. Nie
  zmieniaj plików w innych worktree ani w głównym katalogu repozytorium.
- Na starcie przejrzyj `git worktree list` i `git log --oneline main..<gałąź>`
  pozostałych gałęzi, żeby wiedzieć, co jest w toku, i nie dublować pracy.
- Trzymaj zmiany przy swoim zadaniu: bez masowego formatowania,
  przenoszenia ani refaktoryzacji niezwiązanych plików - to źródło konfliktów.
- Nigdy nie używaj poleceń, które mogą zniszczyć cudzą pracę: `git reset
  --hard` poza własną gałęzią, `git clean`, `git stash`, `git checkout -- .`
  w cudzym katalogu, `git worktree remove`, `git branch -D` na cudzych
  gałęziach. `main` zmieniaj wyłącznie przez `./integrate.sh`.
- Scalanie do `main` robisz sam przez `./integrate.sh` (rebase na `main`,
  sprawdzenia, fast-forward pod blokadą). Kody wyjścia:
  - `0` - gotowe, zmiany są w `main`;
  - `1` - popraw błędy lint/typów/testów, zacommituj, uruchom ponownie;
  - `3` - konflikt przy rebase: rozwiąż go, zachowując sens obu stron
    (w `CHANGELOG.md` i plikach `i18n/locales/*.json` zwykle zostają wpisy
    z obu stron), `git add`, `git rebase --continue`, uruchom ponownie;
  - `4` - główny katalog ma niezacommitowane zmiany: nie ruszaj ich,
    zgłoś użytkownikowi, że scalenie czeka;
  - `5` - `main` przesunął się w trakcie (scalił inny agent): uruchom ponownie.
- Zadanie jest skończone dopiero po udanym `./integrate.sh`.
