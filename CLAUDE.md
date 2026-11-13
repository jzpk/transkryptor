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

**Samouczki**

- Każda nowa funkcja widoczna dla użytkownika (polecenie, okno, przycisk,
  ustawienie) musi być opisana w samouczku w tej samej zmianie: nowy krok
  w pasującym samouczku albo nowy samouczek w `ui/tutorial_content.py`
  (`TUTORIALS`), z tekstami `tutorial.<samouczek>.<krok>.title`/`.text`
  w obu katalogach `i18n/locales/*.json`.
- Krok wskazuje element okna przez `objectName` (z zapasowym celem, np.
  `more_button`, gdy element bywa schowany); nowy widżet, na który wskazuje
  samouczek, dostaje `setObjectName`. Skróty wstawiaj polami `{nazwa}`
  z `shortcuts`, nie na sztywno.
- Gdy funkcja zmienia coś, co opisuje istniejący krok (np. nowe pozycje
  w menu przycisku), popraw też jego tekst.

**Higiena kodu**

- Używaj istniejących pomocników zamiast kopii: `ui.messages.show_error`,
  `MainWindow.show_status`, `fileio.write_atomic`.
- Bez martwego kodu: usuwaj nieużywane moduły i nie zostawiaj
  re-eksportów „dla zgodności importów” - popraw importy.
- Nie nadawaj nazw przesłaniających wbudowane (`Warning`, `type`, `id`...).
- `noqa` i `type: ignore` tylko z kodem reguły i krótkim powodem;
  ruff zgłasza martwe `noqa` (`RUF100`).
- Testy nie dotykają konfiguracji ani danych dewelopera: `tests/conftest.py`
  kieruje katalogi użytkownika i `QSettings` do katalogu tymczasowego.
  Nie używaj `monkeypatch.undo()` (cofa też izolację z fixture'ów) -
  poprawkę na fragment testu rób w `with monkeypatch.context()`.
- Testy korzystają z publicznego API klas. Gdy test potrzebuje wstrzyknąć
  zależność, dodaj do klasy jawny parametr albo metodę, zamiast
  przypisywać do prywatnych atrybutów (`panel._manager = ...`).

**Bezpieczne zmiany mechaniczne**

- Po masowej zamianie (regex, `sed`) przejrzyj `git diff` - zamiana nie
  może trafić w literały napisów (np. klucze tłumaczeń `tr("toolbar.…")`).
- Nie maskuj kodu wyjścia testów potokiem (`pytest ... | tail` zawsze
  zwraca 0) - sprawdzaj wynik `pytest` przed commitem.

## Praca nad zgłoszeniami (GitHub Issues)

Gdy zaczynasz pracę nad zgłoszeniem, od razu nadaj mu etykietę
`in progress`, zanim zmienisz kod:

```sh
gh issue edit <numer> --add-label "in progress"
```

Strona statusu zgłoszeń (`pages/site.js`) pokazuje je wtedy jako „W toku”.
Etykiety nie zdejmuj ręcznie przy zamknięciu - robi to workflow
`.github/workflows/issues.yml`. Jeśli porzucasz zgłoszenie bez zamknięcia,
usuń ją (`--remove-label "in progress"`).

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
4. **Changelog:** opisz zmiany widoczne dla użytkownika w nowym pliku
   `changelog.d/<nazwa>.md` (po polsku, w stylu wpisów `CHANGELOG.md`,
   zasady w `changelog.d/README.md`). `CHANGELOG.md` zmienia tylko
   workflow wydania. Zmiany wyłącznie wewnętrzne (testy, CI,
   refaktoryzacja, instrukcje) oraz zmiany strony projektu nie trafiają do changeloga - tylko zmiany samej aplikacji.
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

6. **Scalenie:** w trybie równoległym uruchom `./integrate.sh` (albo
   `./integrate.sh release/X.Y` dla poprawki do wydanej serii) i doprowadź
   do kodu wyjścia 0. W trybie jednego agenta na `release/X.Y` uruchom
   `./merge-forward.sh X.Y`; na `main` krok pomijasz.

**Nigdy nie wykonuj `git push`.** Wysyłkę na remote robi użytkownik.

## Gałęzie wydań: main i release/X.Y

- `main` to rozwój następnej wersji minor/major (np. 0.9.0).
- `release/X.Y` to poprawki wydanej serii (0.8.2, 0.8.3, ...); z niej
  wychodzą wydania `patch`. Gałąź zakłada workflow „Wydanie” przy wydaniu
  minor/major z `main`.
- Wybór gałęzi: zgłoszenie z milestone'em serii (np. `0.8.2`, `0.8.x`)
  robisz na `release/0.8`; pozostałe na `main`. W razie wątpliwości zapytaj
  użytkownika.
- Scalamy tylko w przód: `release/X.Y` → `main` (`./merge-forward.sh X.Y`,
  wywoływany też przez `./integrate.sh release/X.Y`). Nigdy nie scalaj
  `main` do `release/X.Y` ani nie przenoś na nią commitów z `main`
  (cherry-pick) - wydanie poprawkowe nie może zawierać zmian następnej
  wersji. Poprawkę potrzebną w obu miejscach rób na `release/X.Y`.
- Poprawkę na `release/X.Y` piszesz względem kodu tej serii; konflikt przy
  scalaniu do `main` rozwiązuje się raz, w katalogu scalenia podanym przez
  `merge-forward.sh`.

## Tryb pracy: jeden agent albo kilku równolegle

Na początku zadania ustal tryb poleceniem `git rev-parse --show-toplevel`:

- **Tryb jednego agenta** - jesteś w głównym katalogu repozytorium na
  gałęzi `main` albo `release/X.Y`. Commitujesz bezpośrednio na nią; na
  `release/X.Y` po commicie scalasz ją do `main` (`./merge-forward.sh X.Y`).
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
  gałęziach. `main` i `release/X.Y` zmieniaj wyłącznie przez
  `./integrate.sh` i `./merge-forward.sh`.
- Poprawkę do wydanej serii zaczynasz od worktree na gałęzi z
  `release/X.Y` (`git worktree add -b <nazwa> <katalog> release/X.Y`, jeśli
  środowisko nie założyło go tak samo) i scalasz przez
  `./integrate.sh release/X.Y`.
- Scalanie robisz sam przez `./integrate.sh [release/X.Y]` (rebase na
  celu, sprawdzenia, fast-forward pod blokadą, przy `release/X.Y` także
  scalenie do `main`). Kody wyjścia:
  - `0` - gotowe, zmiany są w celu (i w `main`);
  - `1` - popraw błędy lint/typów/testów, zacommituj, uruchom ponownie;
  - `3` - konflikt przy rebase: rozwiąż go, zachowując sens obu stron
    (w plikach `i18n/locales/*.json` zwykle zostają wpisy z obu stron),
    `git add`, `git rebase --continue`, uruchom ponownie; konflikt przy
    scalaniu do `main`: rozwiąż go w katalogu z komunikatu, `git add`,
    `git commit --no-edit`, uruchom `./merge-forward.sh X.Y`;
  - `4` - katalog z wybraną gałęzią docelową (zwykle główny) ma
    niezacommitowane zmiany: nie ruszaj ich, zgłoś użytkownikowi, że
    scalenie czeka;
  - `5` - cel przesunął się w trakcie (scalił inny agent): uruchom ponownie.
- Zadanie jest skończone dopiero po udanym `./integrate.sh`.
