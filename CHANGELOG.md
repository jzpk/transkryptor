# Historia zmian

Zmiany widoczne dla użytkownika. Nowe wpisy dopisuj w sekcji
„Nieopublikowane” razem z kodem — workflow „Wydanie” nada jej numer wersji
i datę, a jej treść trafi do sekcji „Nowości w tej wersji” not wydania.
Pusta sekcja blokuje wydanie.

## Nieopublikowane

## 0.3.0 — 2026-10-10

- Interfejs po angielsku: w **Ustawieniach…** (zakładka **Wygląd**) można
  wybrać język **Polski**, **English** albo **Zgodny z systemem**
  (domyślnie — polski w polskim systemie, w pozostałych angielski). Zmiana
  działa po ponownym uruchomieniu programu.
- Eksport DOCX używa języka interfejsu (etykiety metryczki, akapit
  „Autor/Data”, tytuł domyślny); import DOCX rozpoznaje dokumenty
  wyeksportowane po polsku i po angielsku.
- Instrukcja użytkownika po angielsku (`docs/user_guide_en.pdf`).
- Motyw jasny i ciemny: w **Ustawieniach…** (zakładka **Wygląd**) można
  wybrać motyw **Jasny**, **Ciemny** albo **Zgodny z systemem** (domyślnie).
  Zmiana działa od razu, bez ponownego uruchamiania.
- Okno **Ustawienia…** jest podzielone na zakładki według tego, czego
  dotyczą ustawienia: **Wygląd**, **Odtwarzacz**, **Notacja**, **Projekt**
  i **Metryczka**.
- W wąskim oknie pasek narzędzi nie ucina już przycisków: te, które się nie
  mieszczą, trafiają do menu **Więcej poleceń** (☰) na końcu paska — najpierw
  rzadziej używane, a **Eksportuj DOCX** zostaje zawsze widoczny. Skróty
  klawiszowe działają także dla schowanych przycisków.
- Długa nazwa pliku nagrania nie poszerza już okna (pełna ścieżka jest
  w podpowiedzi).
- Emoji i inne znaki spoza podstawowego zakresu Unicode (np. znaki
  matematyczne `𝑎`) nie przesuwają już indeksu górnego: DOCX i projekt
  mają indeks górny dokładnie na tych znakach, które widać w edytorze.
  Poprawnie działają też za nimi nawigacja do ostrzeżeń i lista przeglądu
  szkicu ASR.
- Niełamliwa spacja (wklejona albo przeniesiona z DOCX) nie jest już
  zamieniana na zwykłą spację w projekcie i eksporcie DOCX.
- Zapis projektu nie odbiera już uprawnień do pliku: nowy projekt dostaje
  zwykłe prawa (np. czytelny dla zespołu na wspólnym udziale), a ponowny
  zapis zachowuje prawa nadane ręcznie.
- Gdy w oknie zapisu projektu albo eksportu DOCX wpiszesz nazwę bez
  rozszerzenia, a plik z rozszerzeniem `.transkr`/`.docx` już istnieje,
  program pyta, czy go zastąpić, zamiast nadpisywać go bez ostrzeżenia.
- Kopie autozapisu są czytelne tylko dla właściciela konta, a kopia
  porzucona po awarii i nieodzyskana przez 30 dni jest usuwana przy
  starcie.
- Pisanie w długich transkrypcjach jest płynniejsze: licznik słów
  odświeża się po krótkiej przerwie w pisaniu, a zmiana, która nic nie
  zmienia w tekście, nie oznacza pracy jako niezapisanej.
- Eksport DOCX długiej transkrypcji z wieloma znakami w indeksie górnym
  trwa ułamek sekundy zamiast kilkunastu sekund; import dużych plików
  DOCX też jest szybszy.
- Eksport anonimizowany nie oznacza już pracy jako wyeksportowanej:
  ostrzeżenie o niewyeksportowanych zmianach zostaje do pełnego eksportu.
- Zmiana nagrania nie pyta już mylnie „Zapisz / Odrzuć / Anuluj”: tekst
  i metryczka zawsze zostają, a program pyta tylko wtedy, gdy zastępuje
  wczytane nagranie albo usuwa wynik ASR poprzedniego nagrania.
- Po zmianie nagrania „Wstaw szkic ponownie” i lista segmentów nie
  pokazują już szkicu ASR poprzedniego nagrania, a projekt nie zapisuje
  wyniku ASR niepasującego do nagrania.
- Import dużego nagrania i otwarcie projektu nie zamrażają okna: suma
  kontrolna nagrania jest liczona w tle.
- Zamknięcie programu w trakcie pobierania modelu ASR nie kończy się już
  awarią: program pyta, czy przerwać pobieranie, i usuwa częściowo
  pobrane pliki.
- Model ASR jest pobierany z ustalonej wersji repozytorium i każdy plik
  jest sprawdzany sumą kontrolną — model o innej zawartości nie zostanie
  zainstalowany. Pobierane są tylko pliki potrzebne do działania modelu.
- Kolejna transkrypcja ASR w tej samej sesji startuje od razu: model zostaje
  w pamięci (zwalnianej po 10 minutach bezczynności).
- **Anuluj** w trakcie transkrypcji ASR działa natychmiast, także zanim
  pojawi się pierwszy segment (np. przy wczytywaniu modelu albo analizie
  długiego nagrania).
- Animacja w trakcie transkrypcji mniej obciąża procesor.
- Wyszukiwanie wyrażeniem regularnym nie zawiesza już programu: zbyt
  kosztowny wzorzec (np. `(a|aa)+$`) jest przerywany po ułamku sekundy
  z komunikatem pod paskiem wyszukiwania.
- Pisanie przy wielu trafieniach wyszukiwania (np. pojedyncza litera
  w długim tekście) nie zwalnia: podświetlane są tylko trafienia widoczne
  na ekranie, a licznik pokazuje wszystkie.
- **F3** / **Shift+F3** za emoji i innymi znakami spoza podstawowego
  zakresu Unicode przechodzą do właściwego trafienia.
- Automatyczne aktualizacje instalują tylko wydania podpisane kluczem
  autorów: wersja bez podpisu albo z niepasującym podpisem zostaje
  odrzucona z komunikatem, nawet jeśli plik i jego suma kontrolna
  w wydaniu zostały podmienione razem.
- Tuż przed instalacją aktualizacji pobrany plik jest sprawdzany ponownie;
  plik zmieniony od pobrania nie zostanie uruchomiony, a aktualizacja
  pobierze się od nowa przy kolejnym starcie.
- Link „pobierz” w pasku stanu prowadzi wyłącznie do strony wydań na GitHub.

## 0.2.3 — 2026-10-09

- Okno **Ustawienia…** (`Ctrl+,`): skok i auto-cofanie odtwarzacza,
  cofnięcie przed segmentem ASR, czcionka edytora i styl wielokropka.
- Sterowanie odtwarzaczem z klawiatury przy fokusie w edytorze:
  odtwórz/pauza `Ctrl+Spacja` lub `F4`, skok `Alt+←/→`, tempo
  `Ctrl+Shift+,`/`.`; pętla A–B `Ctrl+Shift+A/B/L` i auto-cofanie
  przy wznowieniu po pauzie.
- Kliknięcie segmentu szkicu ASR odtwarza nagranie od jego początku.
- Wyszukiwanie i zamiana (`Ctrl+F`, `Ctrl+H`, `F3`/`Shift+F3`) z opcjami
  wielkości liter, całych słów i wyrażeń regularnych; w zamienniku `^n`
  nadaje literze indeks górny (np. `be^ndzie`), a „Zamień wszystkie” to
  jedno cofnięcie.
- Domyślny zapis pauzy i urwanego słowa to teraz `…` (jeden znak);
  `...` można wybrać w ustawieniach. Walidator rozumie oba zapisy.
  **Dokumenty pisane w starszych wersjach** (z `...`) zostaną oznaczone
  wskazówką VAL-05 — przycisk „Ujednolić wielokropki” nad listą
  ostrzeżeń zamienia je wszystkie jednym krokiem cofania.
