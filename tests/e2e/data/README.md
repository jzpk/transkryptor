# Pliki z poprzednich wydań

Wejście testów e2e: pliki zapisane kodem wydanej wersji programu, takie,
jakie mają użytkownicy po aktualizacji. Nie edytuj ich ręcznie ani nie
zapisuj ponownie bieżącą wersją - test ma sprawdzać odczyt starego formatu.

- `wywiad-v0.6.0.transkr` - projekt (schemat 5) zapisany przez
  `document.project.save_project` z wydania 0.6.0 (tag `v0.6.0`, commit
  `afb4822`): tekst z indeksem górnym, trzech mówców (badacz, informatorka
  z etykietą, sąsiadka), metryczka, kotwice segmentów i słowa, szkic ASR
  z mówcami, stan odtwarzacza z pętlą A-B. Nagranie to
  `tests/fixtures/audio/sample.mp3` (ścieżka względna od pliku projektu).
- `wywiad-v0.6.0.docx` - ten sam dokument wyeksportowany przez
  `export.docx_export.write_docx` z wydania 0.6.0. Legenda mówców ma jeszcze
  pauzę (U+2014) zamiast łącznika.

Pliki z kolejnego wydania dopisuj obok, z numerem wersji w nazwie.
