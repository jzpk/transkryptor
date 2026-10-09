"""Aktualizacje aplikacji z wydań GitHub (bez zależności od Qt).

Podział odpowiedzialności:

- ``releases`` — zapytanie do GitHub Releases API i porównanie wersji;
- ``quota`` — dzienny limit zapytań do API z trwałym stanem w pliku;
- ``download`` — pobranie artefaktu, weryfikacja podpisu sum i sumy SHA256;
- ``signature``, ``keys`` — podpis minisign sum kontrolnych i wbudowane
  klucze publiczne wydań;
- ``install`` — ponowna weryfikacja i uruchomienie instalatora (Windows)
  albo podmiana AppImage;
- ``service`` — przebieg „sprawdź → pobierz” zwracający jeden wynik dla UI.

Wątki i komunikaty należą do ``ui/update_controller.py``.
"""
