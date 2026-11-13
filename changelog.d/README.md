# Fragmenty historii zmian

Każda zmiana widoczna dla użytkownika dodaje tu osobny plik Markdown
z jedną albo kilkoma pozycjami listy, po polsku, w stylu `CHANGELOG.md`:

```markdown
- **Krótki tytuł zmiany:** co użytkownik zobaczy albo zrobi inaczej,
  zawinięte do około 75 znaków w wierszu.
```

- Nazwa pliku to krótki opis po angielsku albo numer zgłoszenia
  (`qt-log.md`, `issue-57.md`). Kolejność w sekcji wersji to kolejność
  nazw plików.
- Poprawka do wydanej wersji (np. 0.8.x) dodaje fragment na gałęzi
  `release/0.8` - po scaleniu do `main` fragment jest i tam, a wydanie
  0.8.x usuwa go z obu gałęzi.
- Workflow „Wydanie” składa wszystkie fragmenty w sekcję
  `## X.Y.Z - RRRR-MM-DD` w `CHANGELOG.md` i usuwa ich pliki. Ten plik
  (`README.md`) zostaje.
