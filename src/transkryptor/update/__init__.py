"""Aktualizacje aplikacji z wydań GitHub (bez zależności od Qt).

Podział odpowiedzialności:

- ``releases`` — zapytanie do GitHub Releases API i porównanie wersji;
- ``quota`` — dzienny limit zapytań do API z trwałym stanem w pliku;
- ``download`` — pobranie artefaktu i weryfikacja sumy SHA256;
- ``install`` — uruchomienie instalatora (Windows) albo podmiana AppImage;
- ``service`` — przebieg „sprawdź → pobierz” zwracający jeden wynik dla UI.

Wątki i komunikaty należą do ``ui/update_controller.py``.
"""
