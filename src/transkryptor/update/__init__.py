"""Aktualizacje aplikacji z wydań GitHub (bez zależności od Qt).

Podział odpowiedzialności:

- ``releases`` - wersja najnowszego wydania z jego podpisu (bez API GitHuba)
  i porównanie wersji;
- ``download`` - pobranie artefaktu, weryfikacja podpisu sum i sumy SHA256;
- ``signature``, ``keys`` - podpis minisign sum kontrolnych i wbudowane
  klucze publiczne wydań;
- ``install`` - ponowna weryfikacja i uruchomienie instalatora (Windows)
  albo podmiana AppImage;
- ``service`` - osobne kroki „sprawdź” i „pobierz” z wynikiem dla UI.

Wątki i komunikaty należą do ``ui/update_controller.py``.
"""
