# Powiadomienia

libli powiadamia użytkowników w aplikacji (przez dzwonek w nagłówku) oraz
e-mailem, dla niewielkiego zestawu zdarzeń. Zachowanie obejmujące całą
platformę konfiguruje się z **Administracja → Ustawienia instytucji → Powiadomienia**.

![Zakładka ustawień powiadomień](static:core/img/help/notifications.pl.png)

## Rodzaje powiadomień

- **Quiz wymaga sprawdzenia** — wysyłane do nauczycieli/administratorów,
  gdy rozwiązanie ucznia wymaga ręcznego ocenienia.
- **Quiz oceniony** — wysyłane do ucznia po ocenieniu jego rozwiązania.
- **Zapisano na kurs** — wysyłane do ucznia w momencie zapisania go na
  kurs (pomijane przy samodzielnym zapisie, ponieważ uczeń właśnie sam to
  zrobił).

## Dostarczanie e-mailem

Każde powiadomienie pojawia się też w rozwijanym menu dzwonka; dostarczanie
e-mailem tego samego zdarzenia to osobna, indywidualna dla każdego
użytkownika opcja rezygnacji dla każdego z trzech rodzajów — każdy
użytkownik sam decyduje, które z nich chce otrzymywać e-mailem, ze
swoich własnych ustawień konta. Nie ma jednego wyłącznika e-maili dla całej
platformy; ta zakładka steruje retencją, a nie dostarczaniem.

## Retencja i czyszczenie

Ustaw **Okno przechowywania (dni)**, przez jaki czas *przeczytane*
powiadomienie jest przechowywane, zanim zostanie zakwalifikowane do
usunięcia, a następnie kliknij **Zapisz ustawienia przechowywania**, aby
je zastosować; nieprzeczytane powiadomienia nigdy nie są usuwane ze
względu na wiek. Powiadomienia dotyczące usuniętego wcześniej rozwiązania
lub kursu (wiersze osierocone) są usuwane zawsze, niezależnie od
ustawionego okna. W sekcji *Wyczyść teraz* na tej zakładce przycisk
**Wyczyść stare powiadomienia teraz** uruchamia czyszczenie od razu — używa
zapisanej wartości retencji, więc najpierw zapisz zmiany. Ewentualnie
polegaj na zaplanowanym zadaniu czyszczącym skonfigurowanym dla Twojego
wdrożenia, które robi to automatycznie z tym samym oknem czasowym.
