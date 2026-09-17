# Szczegółowa analiza w macierzy analitycznej

Macierz analityczna zaczyna od jednej kolumny na każdą sekcję najwyższego
poziomu w kursie, ale prawdziwa siła tkwi w *drążeniu*: rozwijaniu kolumny na
jej elementy podrzędne i zawężaniu siatki tylko do wybranych uczniów. Macierz
otwierasz z panelu **Nauczanie** na pulpicie — klikając **Analityka** przy
kursie — albo z widoku **Moje grupy i kolekcje**, gdzie każda karta grupy ma
odnośnik **Analityka** ograniczony do tej grupy. Karta kolekcji ma go
również, jeśli możesz przeglądać kurs tej kolekcji.

![Wyniki quizów w kursie](static:core/img/help/drill-down.pl.png)

## Rozwijanie kolumny

Każdy nagłówek kolumny, który ma elementy podrzędne, jest wyświetlany jako
odnośnik z małym znacznikiem **▸** po tytule. Kliknij go, aby rozwinąć kolumnę w
miejscu — część otwiera się na rozdziały, rozdział na jednostki i tak dalej.
Wiersz nagłówka zyskuje drugie, zagnieżdżone pasmo obejmujące nowe kolumny
podrzędne.

- Możesz rozwinąć **kilka kolumn naraz**, a każdy element podrzędny da się
  rozwinąć ponownie, tak głęboko, jak sięga struktura kursu.
- Rozwinięty nagłówek grupy zawiera odnośnik **✕ Zwiń**. Kliknij go, aby złożyć
  grupę z powrotem do pojedynczej kolumny.
- Stan rozwinięcia zapisuje się w adresie strony (jako powtarzane wartości
  `expand=`), więc rozwinięty widok można **dodać do zakładek i udostępnić** —
  wyślij współpracownikowi odnośnik, a zobaczy dokładnie te kolumny, które
  otworzyłeś.

Ponieważ pasma kolorów wyliczane są w skali kursu, komórka znaczy to samo przed
rozwinięciem i po nim — drążenie nigdy nie zmienia skali.

## Wybór podzbioru uczniów

Każdy wiersz ucznia ma pole wyboru, a nagłówek ma pole **Zaznacz wszystkich
uczniów**. Zaznacz uczniów, których chcesz, i naciśnij **Zastosuj wybór**:
macierz przelicza się tylko dla wybranego podzbioru, więc średnie
odzwierciedlają wyłącznie wskazanych uczniów. To idealne do sprawdzenia grupy
roboczej albo do porównania kilku uczniów na jednym rozdziale.

- Mała plakietka pokazuje, ilu uczniów jest zaznaczonych, np. **Zaznaczono: 3**.
- Gdy podzbiór jest aktywny, pojawia się odnośnik **Pokaż wszystkich** — użyj
  go, aby wyczyścić podzbiór i wrócić do pełnej listy.
- Zmiana rozwijanej listy zakresu **Uczniowie** rozpoczyna świeży widok i
  odrzuca bieżący podzbiór, więc wybrany zakres i zaznaczony podzbiór nigdy się
  nie kłócą.

Twoje wybory rozwinięcia i podzbioru podróżują z tobą: przenoszą się przez
przełącznik Postęp ↔ Wyniki oraz odnośnik eksportu, więc nigdy nie tracisz
swojego miejsca przy zmianie tego, co mierzy macierz.

## Wyniki i postęp

Kliknij imię i nazwisko ucznia, aby otworzyć jego stronę w bieżącym kursie.
Otwiera się w tym samym widoku, z którego przyszedłeś w macierzy, a nagłówek
nazywa ten widok i ucznia. Przełącznik **Postęp / Wyniki** pod nagłówkiem
zmienia widok bez powrotu:

- **Postęp** pokazuje wszystkie lekcje i quizy. Ukończona lekcja ma ✓,
  nieukończona puste ○, a lekcja nieobowiązkowa jest oznaczona jako
  **Dodatkowa**. Nagłówki rozdziałów liczą ukończone lekcje obowiązkowe, np.
  **lekcje: 1/2**.
- **Wyniki** to tabela quizów oraz części, rozdziałów i sekcji, które je
  zawierają. Quiz z wynikiem pokazuje punkty i procent; każdy inny quiz pokazuje
  swój stan, a quiz czekający na sprawdzenie ma odnośnik do strony sprawdzania.
  Każdy nagłówek, pod którym jest więcej niż jeden quiz, pokazuje w swoim
  wierszu ułamek quizów, np. **1/3**, sumę punktów i procent, a **Cały kurs** na
  górze robi to samo dla całego kursu. Ułamek to liczba quizów, których wynik
  wliczono do sumy, spośród wszystkich quizów w sekcji, więc quiz czekający na
  sprawdzenie nie jest jeszcze wliczony. Sumy i kolory procentów pochodzą z
  macierzy analitycznej, więc wiersz nagłówka zgadza się z komórką tej sekcji w
  macierzy wyników.

Odnośnik **← Analityka** przywraca dokładnie ten zakres, widok, rozwinięte kolumny i
wybór uczniów, z którego przyszedłeś.

## Odpowiedzi na pytania

Na stronie wyników ucznia tytuł każdego rozpoczętego przez niego quizu jest
odnośnikiem. Kliknij go, aby zobaczyć quiz pytanie po pytaniu: odpowiedź ucznia,
klucz tam, gdzie odpowiedź była błędna, punkty i liczbę prób. Pytanie
wielokrotnego wyboru pokazuje **wszystkie** opcje — co uczeń wybrał i które
opcje są poprawne; pytanie z kilkoma częściami układa odpowiedzi ucznia i klucz
w kolumnach. Quiz w toku pokazuje dotychczasowe odpowiedzi. Pytanie czekające
na sprawdzenie prowadzi prosto do strony sprawdzania. Odnośnik **← Wyniki** lub
**← Postęp** (nazywa widok, z którego przyszedłeś) wraca z niezmienionym widokiem
analityki.

## Powiązane tematy

- [Macierz analityczna](analytics)
- [Eksport dziennika ocen](gradebook-export)
- [Sprawdzanie quizów](quiz-review)
