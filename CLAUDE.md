# Instrukcje dla Claude

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
   - `feat:` — nowa funkcja widoczna dla użytkownika,
   - `fix:` — poprawka błędu,
   - `deps:` — zmiana zależności (`pyproject.toml`, `uv.lock`),
   - `docs:` — dokumentacja,
   - `test:` — tylko testy,
   - `refactor:` — zmiana kodu bez zmiany zachowania,
   - `ci:` — workflowy GitHub Actions,
   - `build:` — pakowanie i budowanie wydań,
   - `chore:` — pozostałe prace porządkowe.

   Przykład: `fix: keep toolbar buttons reachable in narrow windows`.

**Nigdy nie wykonuj `git push`.** Wysyłkę na remote robi użytkownik.
