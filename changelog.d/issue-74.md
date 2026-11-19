- **Wnioski z poprawek szkicu:** nowe polecenie „Wnioski z poprawek
  szkicu…” (menu „Otwórz”, zaraz za „Porównaj z…”) porównuje szkic ASR
  z poprawionym tekstem i zbiera wszystkie wnioski naraz: propozycje reguł
  zapisu z gotowym wzorcem, poprawkami w kontekście i liczbą miejsc, które
  pasują do wzorca, ale nie zostały poprawione; słowa, które model zapisuje
  źle zawsze tak samo, do dodania do słownika ASR projektu albo globalnego;
  wstawki pominięte i dodane przez model; usuwaną interpunkcję, zdania
  zmieniane na małą literę i rozwijane skróty - z przyciskiem włączającym
  odpowiednie ustawienie zapisu szkicu - oraz zmiany mówców. Raport zapiszesz
  do CSV albo XLSX. Projekt zapamiętuje szkic po wstawieniu; w starszych
  projektach szkic jest odtwarzany z wyniku ASR (wnioski są wtedy
  przybliżone). Przycisk propozycji reguły w pasku stanu ma pozycję
  „Wszystkie propozycje…”.

- **Uczenie z całego korpusu:** okno „Korpus” ma zakładkę „Wnioski”, która
  porównuje szkice wszystkich projektów folderu z ich tekstem. Wzorce zbyt
  rzadkie w jednym wywiadzie sumują się między projektami (przy każdej
  propozycji widać liczbę projektów), a zaznaczone propozycje trafiają
  prosto do aktywnego profilu notacji, który zespół może wyeksportować.

- **Odrzucone propozycje reguł są pamiętane:** odrzucenie propozycji reguły
  (w pasku stanu albo w oknie wniosków) zapisuje się w profilu notacji -
  propozycja nie wraca po ponownym uruchomieniu programu i trafia do
  eksportu profilu. Dotąd odrzucenie działało tylko do zamknięcia programu.
  Zmiana samego indeksu górnego przy tym samym tekście też liczy się teraz
  jako poprawka szkicu.
