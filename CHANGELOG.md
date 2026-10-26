# Historia zmian

Zmiany widoczne dla użytkownika. Nowe wpisy dopisuj w sekcji
„Nieopublikowane” razem z kodem - workflow „Wydanie” nada jej numer wersji
i datę, a jej treść trafi do sekcji „Nowości w tej wersji” not wydania.
Pusta sekcja blokuje wydanie.

## Nieopublikowane

- **Gotowość do oddania** - nowe okno w menu przycisku eksportu zbiera
  w jednym miejscu to, co zostało do sprawdzenia: ostrzeżenia walidatora,
  niesprawdzone niepewne słowa, otwarte komentarze, akapity bez mówcy (gdy
  dokument ma mówców) i puste pola metryczki. Dwuklik albo Enter na pozycji
  przechodzi do miejsca w tekście lub do pola metryczki. Raport pokazuje się
  też przed każdym eksportem, jeśli jest coś do sprawdzenia (przyciski
  **Eksportuj mimo to** i **Anuluj**); pole „Pokazuj ten raport przed
  eksportem” wyłącza to zachowanie.
- **Rozwiązywanie komentarzy:** przycisk **Rozwiąż** w panelu komentarzy
  (i pozycja w menu kontekstowym tekstu) oznacza komentarz jako rozwiązany,
  a **Otwórz ponownie** przywraca go do otwartych. Filtr **Pokaż:
  Wszystkie / Otwarte / Rozwiązane** nad listą i licznik otwartych
  komentarzy ułatwiają cykl z weryfikatorem. Rozwiązany komentarz zostaje
  w projekcie i w eksporcie DOCX, ale jego fragment nie ma tła, a skróty
  „następny/poprzedni komentarz” prowadzą tylko po otwartych.
- **Reguły fonetyczne z poprawek:** gdy w szkicu ASR kilka razy (domyślnie
  3) poprawisz ten sam wzorzec - np. „e” na „y” albo dopiszesz „n”
  w indeksie górnym - w pasku stanu pojawi się **Propozycja reguły**
  z liczbą poprawek. Kliknięcie otwiera zakładkę **Reguły fonetyczne**
  w ustawieniach z gotową regułą (wzorzec, zamiennik z indeksem górnym,
  przykład), którą można sprawdzić w podglądzie, poprawić i zapisać. Gdy
  wszystkie poprawki mają tę samą literę obok zmiany, wzorzec ją uwzględnia.
  Menu przycisku pozwala odrzucić propozycję do końca pracy programu.

## 0.7.0 - 2026-10-26

- **Zgłoś problem lub pomysł** - nowy przycisk na dole okna (obok „Co
  nowego”) otwiera w przeglądarce formularz na stronie programu. Błąd albo
  pomysł można zgłosić bez konta na GitHubie; wersja programu i systemu są
  wpisane w formularz automatycznie. Program niczego nie wysyła sam.
- Okno **Korpus** (przycisk na pasku narzędzi, skrót `Ctrl+Shift+F` -
  można go zmienić w zakładce **Skróty**) do pracy na wszystkich
  projektach w folderze (także w podfolderach). Domyślnie otwiera folder
  bieżącego projektu, a bieżący projekt jest czytany z edytora - razem
  z niezapisanymi zmianami. Projekty, których nie da się odczytać, są
  pomijane z informacją obok liczby projektów. Wczytywanie folderu,
  wyszukiwanie i liczenie form działają w tle: na ten czas program jest
  zablokowany (nakładka ze spinnerem, postępem i przyciskiem **Przerwij**),
  a przerwanie zostawia poprzednie wyniki.
- **Wyszukiwanie w wielu projektach:** słowo, forma gwarowa albo wyrażenie
  regularne (opcje jak w pasku wyszukiwania, także „Tylko informator”).
  Wyniki to konkordancja: projekt, mówca, kontekst z lewej i prawej strony
  (w obrębie wypowiedzi), trafienie i czas w nagraniu. **Odsłuchaj**
  odtwarza fragment w pętli we własnym odtwarzaczu okna (nagranie okna
  głównego jest wtedy pauzowane), a **Przejdź do miejsca** albo dwuklik
  otwiera projekt (z pytaniem o niezapisane zmiany) i zaznacza trafienie
  w tekście.
- **Słownik form:** lista unikalnych form bieżącego projektu albo całego
  folderu z liczbą wystąpień i projektów, a pod nią wszystkie wystąpienia
  wybranej formy z kontekstem, odsłuchem i przejściem do miejsca. Indeks
  górny jest częścią formy (zapis `be^ndzie`), więc różne zapisy tej samej
  realizacji są widoczne osobno. Kolumna **Formy podobne** i opcja **Tylko
  z podobnymi** wskazują formy różniące się jednym znakiem (np. `jag`
  i `jak`) - kandydatów na niespójność zapisu. Listę form można filtrować
  i wyeksportować do CSV albo XLSX.
- **Zbiorczy eksport metryczek:** zakładka **Metryczki** pokazuje katalog
  nagrań (jeden wiersz na projekt: plik projektu, pola metryczki według
  ustawień, autor i data transkrypcji, mówcy, nagranie z sumą SHA-256,
  liczba słów, słowa informatorów, komentarze) i zapisuje go do CSV (UTF-8,
  czytelny w Excelu) albo XLSX. Eksport **TEI XML** zapisuje cały korpus
  w standardzie TEI P5 (`teiCorpus`): metryczki w nagłówkach, mówcy,
  wypowiedzi z czasami nagrania i indeksem górnym. Opcja **Anonimizuj**
  pomija pola osobowe i etykiety informatorów, jak eksport anonimizowany.
- Menu **Dźwięk** w karcie odtwarzacza: suwak głośności oraz filtry
  odsłuchu - **Wzmocnij ciche fragmenty** (wyrównuje głośność mowy, np.
  cichego informatora daleko od mikrofonu), **Tłum szum niskich tonów**
  (dudnienie, wiatr, brum sieci) i wybór kanału nagrania stereo (oba, tylko
  lewy, tylko prawy - np. osobne mikrofony badacza i informatora). Filtry
  działają na kopii nagrania przygotowywanej w tle (postęp obok przycisku);
  do tego czasu gra oryginał, a po podmianie odtwarzanie trwa dalej z tego
  samego miejsca. Kopia jest zapisywana w pamięci podręcznej (bezstratny
  FLAC, zostają 3 ostatnio używane), więc przy kolejnym otwarciu działa od
  razu. Plik nagrania się nie zmienia, a szkic ASR i fala dźwiękowa
  korzystają z oryginału. Głośność i filtry są pamiętane.
- Przejścia „od problemu do problemu”: **F8** / **Shift+F8** zaznacza
  następne / poprzednie niepewne słowo szkicu ASR i od razu odtwarza je
  w pętli (do pauzy), a pasek stanu pokazuje, które to słowo z ilu i jego
  pewność. **F7** / **Shift+F7** przechodzi do następnego / poprzedniego
  komentarza recenzji (fragment w tekście i komentarz w panelu). Po
  ostatnim miejscu wyszukiwanie wraca na początek tekstu. Skróty można
  zmienić w zakładce **Skróty**.
- Postęp weryfikacji nagrania: przycisk **Sprawdzono N%** w karcie
  odtwarzacza pokazuje, jaka część nagrania jest już sprawdzona.
  **F9** („Oznacz jako sprawdzone do bieżącego miejsca”) oznacza nagranie
  od końca poprzedniego sprawdzonego fragmentu do pozycji odtwarzania,
  a **Shift+F9** („Przejdź do niesprawdzonego miejsca”) przewija nagranie
  i ustawia kursor w tekście tam, gdzie skończyła się weryfikacja - także
  po ponownym otwarciu projektu. Zaznaczony tekst powiązany z nagraniem
  można oznaczyć jako sprawdzony albo niesprawdzony z menu kontekstowego.
  Sprawdzone fragmenty są widoczne na fali dźwiękowej (zielony pasek u góry
  i tło). Postęp jest zapisywany w pliku projektu; zmiana nagrania go
  usuwa (program wcześniej pyta).
- Zapisanie okna **Ustawienia…** nie kasuje już zapamiętanego podpisu
  komentarzy recenzji.
- Bezpieczniejsza aktualizacja na Windows: pobrany instalator jest
  blokowany przed zapisem i usunięciem od chwili sprawdzenia podpisu aż do
  zamknięcia programu, więc między weryfikacją a uruchomieniem (także
  z monitem UAC) inny program nie może go podmienić.
- Komentarze recenzji: do zaznaczonego fragmentu można dodać komentarz
  (menu kontekstowe **Dodaj komentarz…**, skrót `Ctrl+Alt+M` albo panel
  **Komentarze** na pasku narzędzi) z podpisem autora i datą, a na
  komentarz - odpowiedzieć. Komentowane fragmenty mają w tekście tło, po
  najechaniu widać treść; z panelu można przejść do fragmentu i odsłuchać
  go z nagrania. Komentarz przesuwa się razem z tekstem przy edycji,
  a gdy fragment zostanie usunięty, komentarz zostaje z cytatem. Komentarze
  są zapisywane w pliku projektu - projektu z komentarzami nie otworzy już
  starsza wersja programu.
- Eksport DOCX zawiera komentarze recenzji jako komentarze Worda przy
  komentowanym fragmencie, z odpowiedziami w treści komentarza. Eksport
  anonimizowany i pozostałe formaty komentarzy nie zawierają.
- **Porównaj z…** (menu przycisku **Otwórz**): bieżący projekt można
  porównać z innym plikiem projektu tego samego nagrania, np. wersją
  poprawioną przez weryfikatora. Obie wersje są widoczne obok siebie -
  po lewej bieżący dokument, po prawej porównywana (tylko do odczytu) -
  a panel **Porównanie** wymienia zmiany: wstawienia, usunięcia, zmiany
  tekstu, indeksu górnego i mówcy akapitu. Kliknięcie zmiany zaznacza ją
  w obu wersjach, **Odsłuchaj** odtwarza fragment z nagrania. Zmiany
  przyjmuje się albo odrzuca pojedynczo lub wszystkie naraz, a każdą
  decyzję można cofnąć (`Ctrl+Z`). Na czas porównania bieżący tekst jest
  tylko do odczytu; **Zakończ porównanie** zostawia dokument z przyjętymi
  zmianami.

## 0.6.0 - 2026-10-24

- Import DOCX dużego dokumentu jest kilkukrotnie szybszy (np. 3000
  akapitów - ok. 0,3 s zamiast 2 s).
- **Ustawienia…**: sekcje (Wygląd, Odtwarzacz, … ASR, Dziennik logów) są
  listą po lewej stronie okna, zawsze widoczną w całości - wcześniej
  ostatnie zakładki chowały się za krawędzią okna. Długie sekcje (np. ASR)
  przewijają się, zamiast ściskać pola.
- **Liczba mówców** jest też w panelu **Szkic ASR** (krok 3, nad
  przyciskiem transkrypcji), gdy podział na mówców jest włączony - można ją
  szybko zmienić przed rozpoznaniem każdego nagrania. Wybór jest pamiętany
  i ten sam co w **Ustawieniach…**.
- Więcej żartobliwych komunikatów w trakcie transkrypcji: pula wzrosła
  z 30 do 50, więc teksty rzadziej się powtarzają.
- Dziennik błędów: program zapisuje lokalnie plik `transkryptor.log`
  z informacjami technicznymi o błędach i awariach (także procesu ASR),
  które pomagają znaleźć przyczynę problemu. Nic nie jest wysyłane -
  plik można samemu dołączyć do zgłoszenia na GitHubie. Dziennik jest po
  angielsku i nie zawiera tekstu transkrypcji, metryczki, kontekstu ASR ani
  nazw i ścieżek plików użytkownika. Dostęp do niego daje nowa zakładka
  **Ustawienia…** → **Dziennik logów** (dla zaawansowanych użytkowników):
  odnośnik do folderu dziennika i przycisk **Zgłoś problem…** (formularz
  zgłoszenia w przeglądarce).
- Ostrzeżenia w tekście: problemy z notacją są podkreślone falistą linią
  bezpośrednio w edytorze (pomarańczową - ostrzeżenia, szarą - wskazówki),
  a po najechaniu myszą widać opis. Podkreślenia nie trafiają do DOCX.
- Nowe reguły walidatora: `(!)` / `(?)` przylegające do następnego słowa
  (VAL-06), kilka spacji z rzędu (VAL-07), spacja przed `]` (VAL-08),
  zagnieżdżone dopiski `[ [ ] ]` (VAL-09) i indeks górny na znaku innym niż
  `m`, `n`, `u` (VAL-10). Wskazówkę o `m`/`n`/`u` bez indeksu górnego
  (VAL-11) można włączyć w ustawieniach - domyślnie jest wyłączona.
- W **Ustawieniach…** nowa zakładka **Walidator**: każdą regułę można
  włączyć albo wyłączyć.
- **Ignoruj tutaj** w menu kontekstowym edytora i listy ostrzeżeń pomija
  jedno konkretne ostrzeżenie; pozostałe wystąpienia tej reguły są nadal
  zgłaszane. Zignorowanie jest zapisywane w pliku projektu. Projekty
  z wersji 0.5.0 otwierają się bez zmian; projektu zapisanego w nowej
  wersji nie otworzy już wersja 0.5.0.
- Własne reguły fonetyczne: w **Ustawieniach…** nowa zakładka **Reguły
  fonetyczne**. Regułę opisuje wzorzec (wyrażenie regularne na słowie albo
  parze sąsiednich słów) i zamiennik, w którym `^m` oznacza „m” w indeksie
  górnym. Podgląd pokazuje działanie na przykładzie i liczbę dopasowań
  w bieżącym tekście. Własne reguły pojawiają się w panelu **Szkic ASR**
  razem z wbudowanymi; zestaw można wyeksportować do pliku `.toml`
  i zaimportować u innego badacza.
- Nowe reguły wbudowane: redukcja „ł” między samogłoskami
  (wiedziałam → wiedziaam), udźwięcznienie na granicy słów (kiedyś jak →
  kiedyź jak, jak nowy → jag nowy), wygłosowe „ch” → „h” (tych → tyh),
  końcowe „ą” → „óᵐ” (są → sóᵐ) i labializacja w środku słowa
  (kosa → kᵘosa). Mają orientacyjną pewność i domyślnie nie są stosowane
  automatycznie - ich dopasowania pojawiają się jako propozycje.
- Gdy propozycje dwóch reguł dotyczą tego samego fragmentu, pierwszeństwo
  ma reguła zaznaczona do automatycznego stosowania.
- Błędna reguła w pliku reguł nie blokuje programu: przy starcie pojawia się
  komunikat ze wskazaniem reguły i pola, a pozostałe reguły działają.
  Wzorzec, którego dopasowanie trwa zbyt długo, jest przerywany bez
  zawieszania okna.
- Własne skróty klawiaturowe: w **Ustawieniach…** nowa zakładka
  **Skróty** pozwala zmienić skrót każdego znacznika notacji, indeksu
  górnego, odtwarzacza, wyszukiwania i poleceń projektu oraz dodać skrót
  zapasowy (np. pedał nożny). Program ostrzega przed zapisem, gdy skrót jest
  już zajęty przez inną akcję albo przez edycję tekstu (kopiuj, cofnij…).
  Nowe skróty działają od razu, a podpowiedzi przycisków pokazują bieżące
  skróty. **Przywróć wszystkie domyślne** wraca do skrótów fabrycznych.
- Wstawki: w zakładce **Wstawki** można zapisać często używane formy, np.
  `so^m` (`^m` - „m” w indeksie górnym), i przypisać im skróty - kolejne
  wstawki dostają podpowiedź `Alt+1`…`Alt+9`. Wstawkę wstawia się skrótem
  albo z menu **Wstawki** na pasku narzędzi; jedno cofnięcie usuwa ją
  w całości.
- Autouzupełnianie (domyślnie wyłączone, **Ustawienia…** → **Notacja**):
  po wpisaniu dwóch liter edytor podpowiada pasujące wstawki i słowa użyte
  już w tekście; Enter lub Tab wstawia podpowiedź.
- Tekst powiązany z nagraniem: szkic ASR zapamiętuje, z którego miejsca
  nagrania pochodzi każde zdanie (segment). **Ctrl+klik** w tekst albo skrót
  **Ctrl+Shift+Spacja** („Odtwórz od miejsca w tekście”) odtwarza nagranie od
  początku segmentu (z wyprzedzeniem z ustawień). Podczas odtwarzania
  podświetlany jest segment odpowiadający bieżącemu miejscu, a edytor
  przewija się za nim - przewijanie można wyłączyć w **Ustawieniach…**
  (zakładka **Odtwarzacz**). Powiązania przesuwają się razem z edycją
  tekstu i są zapisywane w pliku projektu.
- Ręczne znaczniki czasu: skrót **Ctrl+Shift+T** wstawia w miejscu kursora
  znacznik bieżącej pozycji nagrania (mały trójkąt w tekście). **Ctrl+klik**
  obok znacznika odtwarza nagranie dokładnie od zapisanego czasu. Znacznik
  usuwa się z menu kontekstowego; nie trafia do eksportu DOCX. Oba nowe
  skróty można zmienić w zakładce **Skróty**.
- Niepewne słowa: szkic ASR zna czas i pewność każdego słowa. Słowa,
  których model nie jest pewien, są podkreślone czerwonymi kropkami (inaczej
  niż ostrzeżenia notacji); po najechaniu myszą widać pewność.
  **Ctrl+klik** w słowo odtwarza dokładnie to słowo w pętli (do pauzy).
  Poprawione słowo traci podkreślenie. Podkreślenia nie trafiają do DOCX.
  W **Ustawieniach…** (zakładka **ASR**) można wyłączyć podkreślenia,
  zmienić próg pewności (domyślnie 40%, wartość orientacyjna) albo wyłączyć
  rozpoznawanie słów, które wydłuża transkrypcję.
- Rozpoznanie fragmentu: przycisk **Rozpoznaj fragment A-B** w panelu
  **Szkic ASR** rozpoznaje tylko fragment nagrania między punktami A i B
  pętli. Wynik trafia w miejsce kursora (albo zastępuje zaznaczony tekst)
  z regułami fonetycznymi i powiązaniem z czasem nagrania; jedno cofnięcie
  usuwa go w całości. Szkic całego nagrania i lista segmentów się nie
  zmieniają.
- Fala dźwiękowa pod suwakiem odtwarzacza: widać ciszę, pauzy i głośne
  fragmenty. Klik na fali przewija nagranie, przeciągnięcie ustawia pętlę
  A-B, **Ctrl** + kółko myszy powiększa. Na fali są też segmenty szkicu ASR
  (zielone - pewne, pomarańczowe - niepewne) i ręczne znaczniki czasu. Fala
  powstaje w tle bez blokowania okna (godzina nagrania - kilkanaście
  sekund) i jest zapamiętywana w pamięci podręcznej, więc przy kolejnym
  otwarciu pojawia się od razu. Falę można zwinąć; wybór jest pamiętany.
- Szybsze wstawianie długiego szkicu ASR: przy godzinnym nagraniu
  wyszukiwanie kolidujących propozycji zapisu fonetycznego nie spowalnia
  już okna na kilka sekund.
- Mówcy wypowiedzi: skrót **Alt+Shift+1…9** przypisuje bieżącemu akapitowi
  (albo wszystkim zaznaczonym) mówcę o tym numerze na liście, ponowne
  użycie albo **Alt+Shift+0** zdejmuje przypisanie; to samo jest w menu
  kontekstowym edytora (**Mówca**). Etykieta `B:` / `I:` jest widoczna obok
  akapitu, ale nie jest częścią tekstu, a jedno cofnięcie przywraca stan
  sprzed przypisania. Listę mówców (klucz, opis, rola: badacz, informator
  albo inny; domyślnie `B` i `I`) edytuje się w metryczce przyciskiem
  **Mówcy…**. Mówcy są zapisywani w pliku projektu; projektu zapisanego
  w nowej wersji nie otworzy starsza wersja programu.
- Eksport DOCX zapisuje każdy wiersz tekstu jako osobny akapit, a akapit
  z mówcą zaczyna się pogrubioną etykietą `B:`; legenda mówców trafia do
  metryczki (w eksporcie z anonimizacją bez opisów informatorów). Import
  DOCX zachowuje akapity i rozpoznaje mówców z takiego dokumentu.
- Gdy dokument ma mówców, licznik słów pokazuje też liczbę słów
  informatorów, pasek wyszukiwania ma pole **Tylko informator**, a nowa
  wskazówka walidatora (VAL-12) wskazuje akapity bez mówcy.
- Nowe formaty eksportu: w menu przycisku **Eksportuj DOCX** pozycja
  **Eksportuj jako…** zapisuje transkrypcję jako ODT, PDF, zwykły tekst
  (TXT), plik ELAN (`.eaf`), Praat TextGrid oraz napisy SRT i WebVTT.
  W formatach tekstowych indeks górny można zapisać znakami Unicode
  (`ᵐ ⁿ ᵘ`, domyślnie) albo oznaczeniem `^m`. ELAN, Praat i napisy
  korzystają z powiązania tekstu z nagraniem (szkic ASR, znaczniki czasu):
  każdy mówca ma osobną warstwę, a fragmenty bez czasu dostają czas
  wyznaczony z sąsiednich kotwic albo są pomijane - raport po eksporcie
  wymienia takie fragmenty. Znaczniki `[mm:ss]` wierszy szkicu ASR nie
  trafiają do adnotacji. Plik ELAN wskazuje nagranie. Wybrany format
  i opcje są pamiętane; DOCX pozostaje głównym formatem.
- Szablon eksportu DOCX: w **Ustawieniach…** nowa zakładka **Eksport**
  pozwala wskazać plik `.docx` instytucji (czcionki, marginesy, nagłówek,
  stopka, logo). Placeholdery `{{sygnatura}}`, `{{badacz}}`,
  `{{miejscowosc}}` itd. w tekście, tabelach, nagłówku i stopce są
  wypełniane metryczką (w eksporcie z anonimizacją pola osobowe są puste),
  `{{transkrypcja}}` wskazuje miejsce tekstu, a `{{metryczka}}` - tabelę
  metryczki. Szablon jest sprawdzany przy wyborze (nieznane placeholdery,
  uszkodzony plik); gdy nie da się go otworzyć, eksport powstaje na
  szablonie wbudowanym z ostrzeżeniem. W tej samej zakładce są domyślne
  opcje indeksu górnego i fragmentów bez czasu.
- Czcionka Charis SIL (licencja SIL Open Font License) jest dołączona do
  programu i jest domyślną czcionką tekstu w edytorze i eksporcie: dobrze
  wyświetla znaki fonetyczne i indeks górny `ᵐ ⁿ ᵘ`. PDF zawiera czcionkę,
  a w DOCX i ODT zapisana jest jej nazwa (na komputerze bez Charis SIL
  edytor dokumentów podstawi inną). Inną czcionkę można wybrać jak dotąd
  w **Ustawieniach…** (zakładka **Wygląd**).
- Podział szkicu ASR na mówców: po transkrypcji program rozpoznaje, kto
  mówi, i każda wypowiedź staje się osobnym akapitem ze znacznikiem czasu
  `[mm:ss]` i mówcą - w edytorze i w eksporcie DOCX (pogrubiona etykieta
  `B:` / `I:`). Ten podział zastępuje dzielenie szkicu na wersy co 30 sekund.
  Mówcy są przypisywani w kolejności pojawiania się w nagraniu: pierwszy
  głos to pierwszy mówca z listy (domyślnie `B`), drugi - `I`, a kolejne
  głosy dostają nowych informatorów `I2`, `I3`… Przypisanie można poprawić
  jak dotąd (**Alt+Shift+1…9**, **Mówcy…**). Opcja jest w **Ustawieniach…**
  (zakładka **ASR**, domyślnie włączona) i wymaga jednorazowego pobrania
  modelu podziału na mówców (ok. 28 MB, za zgodą użytkownika) - bez niego
  pole jest zablokowane, a szkic dzieli się jak dotąd. Model działa w pełni
  lokalnie. Rozpoznanie fragmentu A-B nie dzieli tekstu na mówców.
  Podział wychwytuje także szybkie wymiany pytań i jednowyrazowych
  odpowiedzi w wywiadzie („Zajęcie?” - „Rolnik.”), a zmianę mówcy stawia
  na końcu zdania. Pod opcją można podać **Liczbę mówców** w nagraniu
  (domyślnie 2 - badacz i informator, do wyboru 2-8 albo
  **Automatycznie**). Podana liczba daje pewniejszy podział niż tryb
  automatyczny, który sam ocenia liczbę głosów.
- Aktualizacje są sprawdzane przy każdym uruchomieniu, na ekranie
  startowym: najpierw „Sprawdzanie dostępnych aktualizacji…”, a gdy jest
  nowa wersja - postęp jej pobierania. **Pomiń** otwiera program od razu,
  a pobieranie kończy się w tle. Gotowa wersja jak dotąd czeka w pasku stanu
  z przyciskiem **Uruchom ponownie i zaktualizuj**. Limit zapytań do serwera
  wydań wzrósł z 2 do 5 na dobę. Przycisk **Sprawdź aktualizacje** i odnośnik
  „pobierz” w pasku stanu zostały usunięte.

## 0.5.0 - 2026-10-18

- Szkic ASR jest dzielony na wersy obejmujące najwyżej 30 sekund nagrania,
  a każdy wers zaczyna się znacznikiem czasu, np. `[01:30]` (od godziny
  nagrania `[1:02:03]`). Podział i znaczniki trafiają też do eksportu DOCX
  zamiast jednego bloku tekstu. W starszych projektach wystarczy użyć
  **Wstaw szkic ponownie**.

## 0.4.0 - 2026-10-11

- Wybór modelu ASR: w panelu **Szkic ASR** można wybrać **small**
  (ok. 0,5 GB, szybki, dla słabszych komputerów), **medium** (domyślny)
  albo **large-v3** (ok. 3,1 GB, najdokładniejszy, wymaga ok. 6 GB RAM).
  Każdy model pobiera się osobno, za zgodą; wybór jest pamiętany. Gdy model
  potrzebuje więcej pamięci, niż ma komputer, program ostrzega przed
  transkrypcją.
- Pobrany model można usunąć przyciskiem **Usuń model…** - panel pokazuje,
  ile miejsca odzyskano; pozostałe modele działają dalej.
- Karta graficzna NVIDIA: jeśli zainstalowano biblioteki CUDA 12 i cuDNN 9,
  szkic powstaje na GPU, wielokrotnie szybciej. Bez nich program sam
  przechodzi na procesor i informuje o tym pod przyciskiem transkrypcji.
  W **Ustawieniach…** (nowa zakładka **ASR**) można wymusić pracę tylko na
  procesorze i wskazać inny katalog modeli (np. dysk zewnętrzny).
- Kontekst nagrania i słownik: przed transkrypcją można podać krótki opis
  nagrania (do 200 znaków, wypełniany z miejscowości i gminy w metryczce)
  oraz słownik projektu - nazwy miejscowości, nazwiska, wyrazy gwarowe.
  Pomagają modelowi poprawnie zapisać nazwy własne. Słownik wspólny dla
  wszystkich nagrań ustawia się w **Ustawieniach…** (zakładka **ASR**).
- Plik projektu zapisuje kontekst nagrania, słownik projektu i model użyty
  do szkicu. Projekty z wersji 0.3.0 otwierają się bez zmian; projektu
  zapisanego w nowej wersji nie otworzy już wersja 0.3.0.
- W wąskim oknie schowane przyciski notacji trafiają do menu **Więcej
  poleceń** (☰) tuż za widocznymi znacznikami, przed **Szkic ASR**, a nie
  na koniec paska. Schowane narzędzia i polecenia projektu pozostają
  w menu ☰ na końcu paska.
- Historia zmian w programie: przycisk **Co nowego** w lewym dolnym rogu
  okna (obok numeru wersji) otwiera okno z opisem zmian w kolejnych
  wersjach.
- Transkrypcja fragmentami: w **Ustawieniach…** (zakładka **ASR**) można
  włączyć rozpoznawanie długiego nagrania kilkuminutowymi fragmentami
  ciętymi w ciszy. Zużycie pamięci RAM nie rośnie wtedy z długością
  nagrania - pomaga, gdy szkic z nagrania ponad godzinnego kończy się
  błędem `mkl_malloc: failed to allocate memory`. Domyślnie wyłączone.
- Gdy transkrypcji zabraknie pamięci, program mówi o tym wprost i radzi
  włączyć transkrypcję fragmentami albo zamknąć inne programy, zamiast
  proponować ponowne pobranie modelu.

## 0.3.0 - 2026-10-10

- Interfejs po angielsku: w **Ustawieniach…** (zakładka **Wygląd**) można
  wybrać język **Polski**, **English** albo **Zgodny z systemem**
  (domyślnie - polski w polskim systemie, w pozostałych angielski). Zmiana
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
  mieszczą, trafiają do menu **Więcej poleceń** (☰) na końcu paska - najpierw
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
  jest sprawdzany sumą kontrolną - model o innej zawartości nie zostanie
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

## 0.2.3 - 2026-10-09

- Okno **Ustawienia…** (`Ctrl+,`): skok i auto-cofanie odtwarzacza,
  cofnięcie przed segmentem ASR, czcionka edytora i styl wielokropka.
- Sterowanie odtwarzaczem z klawiatury przy fokusie w edytorze:
  odtwórz/pauza `Ctrl+Spacja` lub `F4`, skok `Alt+←/→`, tempo
  `Ctrl+Shift+,`/`.`; pętla A-B `Ctrl+Shift+A/B/L` i auto-cofanie
  przy wznowieniu po pauzie.
- Kliknięcie segmentu szkicu ASR odtwarza nagranie od jego początku.
- Wyszukiwanie i zamiana (`Ctrl+F`, `Ctrl+H`, `F3`/`Shift+F3`) z opcjami
  wielkości liter, całych słów i wyrażeń regularnych; w zamienniku `^n`
  nadaje literze indeks górny (np. `be^ndzie`), a „Zamień wszystkie” to
  jedno cofnięcie.
- Domyślny zapis pauzy i urwanego słowa to teraz `…` (jeden znak);
  `...` można wybrać w ustawieniach. Walidator rozumie oba zapisy.
  **Dokumenty pisane w starszych wersjach** (z `...`) zostaną oznaczone
  wskazówką VAL-05 - przycisk „Ujednolić wielokropki” nad listą
  ostrzeżeń zamienia je wszystkie jednym krokiem cofania.
