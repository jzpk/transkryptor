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

## Zasady projektowe: bez narastającego długu

Pisząc nowy kod albo rozbudowując istniejący, trzymaj się tych zasad od
razu - nie odkładaj ich na „późniejszy refaktor”. Jeśli zmiana przekroczyłaby
któryś limit, najpierw wydziel część kodu, potem dopisuj funkcję.

**Rozmiar i odpowiedzialność**

- Jedna klasa = jedna odpowiedzialność. Moduł powyżej ~500 linii albo klasa
  z kilkoma niezależnymi obszarami (np. pobieranie modelu i transkrypcja)
  to sygnał do podziału na osobne moduły/klasy.
- Widżet z kilkoma częściami składaj z sekcji (wzorzec: `AsrPanel` +
  `ModelSection`/`TranscriptionSection`/`ReviewSection`); kontener tylko
  układa sekcje i przekazuje ich sygnały.
- `__init__` widżetu tworzy stan i wywołuje metody `_build_*`
  (`_build_layout`, `_connect_signals`) - bez setek instrukcji w konstruktorze.
- Złożoność funkcji pilnuje ruff (`C901`, próg 15) - nie podnoś progu
  ani nie dodawaj `noqa: C901`; podziel funkcję na etapy.

**Zależności**

- `MainWindow` to tylko korzeń kompozycji. Obsługa nowych zdarzeń
  domenowych trafia do kontrolera (`*_controller.py`), nie do okna.
- Konstruktor kontrolera: najwyżej ~8 parametrów. Powiązane zależności
  grupuj w obiekt parametrów (np. `ProjectAnnotations`, `MetadataWidgets`),
  zamiast konkretnych widżetów przekazuj wąskie funkcje
  (`Callable[[], QDate]`) albo `Protocol`, a zdarzenia ogłaszaj sygnałami
  (`SessionEvents`), nie callbackami w konstruktorze.
- Funkcja z więcej niż ~6 parametrami dostaje dataclass z opcjami.
- Warstwy: `asr`, `corpus`, `document`, `notation`, `update`, `settings`,
  `fileio` nie importują Qt ani `transkryptor.ui` (pilnuje
  `tests/test_layers.py`). Wspólne narzędzia (np. zapis atomowy) trafiają
  do modułu ogólnego (`fileio.py`), a nie do modułu domenowego, z którego
  importuje je UI.

**Rozszerzalność**

- Nowe pole ustawień: wpis `_Field` w `settings.py` (cechy pola jako
  atrybuty `_Field`, nigdy warunki na nazwę pola) i obsługa w odpowiedniej
  stronie `settings_pages.py` (`load`/`apply`). Nowa zakładka ustawień to
  nowa klasa strony, nie kolejne pola w `SettingsDialog`.
- Nowy format eksportu: wpis w rejestrze `export/registry.py`.

**Higiena kodu**

- Używaj istniejących pomocników zamiast kopii: `ui.messages.show_error`,
  `MainWindow.show_status`, `fileio.write_atomic`.
- Bez martwego kodu: usuwaj nieużywane moduły i nie zostawiaj
  re-eksportów „dla zgodności importów” - popraw importy.
- Nie nadawaj nazw przesłaniających wbudowane (`Warning`, `type`, `id`...).
- `noqa` i `type: ignore` tylko z kodem reguły i krótkim powodem;
  ruff zgłasza martwe `noqa` (`RUF100`).
- Testy korzystają z publicznego API klas. Gdy test potrzebuje wstrzyknąć
  zależność, dodaj do klasy jawny parametr albo metodę, zamiast
  przypisywać do prywatnych atrybutów (`panel._manager = ...`).

**Bezpieczne zmiany mechaniczne**

- Po masowej zamianie (regex, `sed`) przejrzyj `git diff` - zamiana nie
  może trafić w literały napisów (np. klucze tłumaczeń `tr("toolbar.…")`).
- Nie maskuj kodu wyjścia testów potokiem (`pytest ... | tail` zawsze
  zwraca 0) - sprawdzaj wynik `pytest` przed commitem.

## Na koniec każdego zadania zmieniającego kod

Wykonaj kolejno, zanim zgłosisz, że praca jest skończona:

1. **Lint i formatowanie:** `uv run ruff check .` oraz `uv run black --check .`
   (przy błędach formatowania uruchom `uv run black .`).
2. **Typy:** `uv run mypy`.
3. **Testy:** `uv run pytest -q` oraz testy end-to-end
   `uv run pytest -q --e2e tests/e2e`. Wszystkie muszą przechodzić; jeśli
   coś nie przechodzi, napraw to albo jasno zgłoś, co i dlaczego. Gdy
   zmiana formatu wyjścia jest zamierzona, odśwież wzorce
   (`--update-golden`) i sprawdź ich różnicę w `git diff`.
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
