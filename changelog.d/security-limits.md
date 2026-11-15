- **Bezpieczniejsze pobieranie modelu i aktualizacji:** program przerywa
  pobieranie modelu rozpoznawania mowy albo nowej wersji, gdy serwer
  wysyła więcej danych, niż powinien, zamiast zapisywać je do końca
  i dopiero wtedy odrzucać. Uszkodzony albo podstawiony serwer nie zapełni
  już dysku. Aktualizacja pobiera pliki tylko z serwerów GitHuba - inny
  adres przerywa ją z komunikatem.
- **Bezpieczniejsze otwieranie paczek:** paczka `.tkpack` jest teraz
  rozpakowywana dopiero po zatwierdzeniu okna z ustawieniami z paczki.
  „Anuluj” nie zostawia plików na dysku ani nie nadpisuje istniejących.
  Spreparowana albo uszkodzona paczka (np. bardzo duża po rozpakowaniu)
  jest odrzucana z komunikatem, zamiast zajmować całą pamięć, a nagranie
  z paczki jest sprawdzane sumą kontrolną. Pliki o nazwach, których nie da
  się zapisać w Windows (np. `CON`, `NUL`), dostają bezpieczną nazwę.
