# Elementy interaktywne

Grupa **Interaktywne** zawiera dziewięć elementów samosprawdzających i
odsłaniających, dostępnych wyłącznie w **lekcjach** — dodajesz je z edytora
jednostki przez **Dodaj element**; grupa jest niedostępna podczas edycji
quizu. Większość z nich to elementy samosprawdzające: uczeń sam sprawdza
swoją pracę na miejscu, a rodzinna konwencja tych widżetów to zablokowany
formularz bez przycisku zatwierdzania — nie ma więc nic do wysłania ani do
ocenienia, a te elementy **nie przyznają punktów**. Podobnie jak [typy
elementów treści](content-editors), można je zagnieżdżać wewnątrz Zakładek
i Kolumn.

![Lekcja z elementem interaktywnym „Pokaż więcej”](static:core/img/help/interactive.pl.png)

## {el:revealgate} Pokaż więcej

Cienka bramka z polem **Tekst przycisku** (domyślnie *Pokaż więcej*,
wyświetlanym jako podpowiedź, gdy pole zostanie puste). Ukrywa elementy
znajdujące się po niej w konspekcie, dopóki uczeń nie kliknie jej przycisku
— bez sprawdzania po stronie serwera, bez punktów, sam podział typu
kliknij-i-odsłoń. Użyj jej, aby rozłożyć lekcję w czasie tak, by dalszy
materiał nie zdradzał wcześniejszej części.

## {el:fillgate} Uzupełnij i potwierdź

Bramka odsłaniająca, której wyzwalaczem jest luka do uzupełnienia zamiast
zwykłego przycisku. Zapisz **Treść z lukami**, oznaczając lukę jako
`{{odpowiedź}}`, używając `|` do oddzielenia akceptowanych wariantów (np.
`{{Paryż|paryż}}`) — ta sama składnia co w pytaniach typu [Uzupełnij
luki](quiz-editors). Poprawna, sprawdzana po stronie serwera odpowiedź
odsłania kolejne elementy; nie przyznaje punktów.

## {el:switchgate} Wybierz i zatwierdź

Bramka odsłaniająca, której wyzwalaczem jest przełączany w linii widżet
"Wybierz ▾" zamiast wpisywanej odpowiedzi. Zapisz **Treść z wyborem**,
oznaczając miejsce wyboru jako `{{choice}}` (dokładnie raz), a następnie
uzupełnij listę **Opcji** widżetu i zaznacz poprawną. Poprawny, sprawdzany
po stronie serwera wybór odsłania kolejne elementy; nie przyznaje punktów.

## {el:switchgrid} Siatka przełączników

Element samosprawdzający złożony z jednej lub kilku linii przeplatających
statyczny tekst z klikalnymi przełącznikami: zapisz każdą linię, wstawiając
`{{choice}}` w miejscu, gdzie ma się pojawić przełącznik (blok przełącznika
powstaje dla każdego takiego znacznika), a następnie uzupełnij opcje
każdego przełącznika i zaznacz poprawną. Dodawaj kolejne linie przyciskiem
**Dodaj wiersz**. Cała siatka jest sprawdzana łącznie, z informacją zwrotną
przy każdym przełączniku w miarę klikania przez ucznia; nie odsłania ani
nie blokuje niczego i nie przyznaje punktów.

## {el:filltable} Tabela do uzupełnienia

Edytor tabeli — ta sama siatka, przełączniki wiersza/kolumny nagłówkowej,
style obramowania oraz narzędzia scalania/rozdzielania komórek co w
elemencie [Tabela](content-editors) — z jednym dodatkiem: przycisk paska
narzędzi **Komórka z odpowiedzią** zamienia komórkę na pole przyjmujące ciąg
akceptowanej odpowiedzi zamiast treści sformatowanej. Komórki statyczne
pozostają edytowalnym tekstem/wzorem jak w zwykłej tabeli; komórki z
odpowiedzią są sprawdzane po stronie serwera dla każdej komórki osobno, w
miarę wpisywania przez ucznia. Zaznacz zakres komórek kombinacją
Shift+kliknięcie albo rozszerzaj go pole po polu skrótem
**Alt+Shift+strzałka**, a następnie kliknij **Scal komórki**, aby połączyć
zaznaczenie w jedną komórkę — przetrwa tylko komórka w lewym górnym rogu,
razem ze swoim rodzajem, więc scalenie obejmujące komórkę z odpowiedzią lub
komórkę z obrazem usuwa jej akceptowaną odpowiedź lub obraz razem z resztą
zaznaczenia; jeśli którakolwiek z pochłanianych komórek nie była pusta,
najpierw zostaniesz poproszony o potwierdzenie. **Rozdziel komórkę** cofa
scalenie, zwracając zwolnione komórki jako puste komórki statyczne.
**Komórka nagłówkowa** przełącza pojedynczą komórkę między zwykłym a
nagłówkowym stylem; jest wyszarzona — niedostępna, dopóki komórkę obejmuje
opcja wiersza lub kolumny nagłówkowej — gdy komórkę obejmuje już
**Wiersz nagłówkowy** lub **Kolumna nagłówkowa**. W tabeli z włączoną opcją
**Kolumna nagłówkowa** scalenie usuwające pierwszą komórkę wiersza sprawia,
że kolejna komórka tego wiersza staje się dla uczniów nagłówkiem, mimo że
edytor nadal pokazuje ją jako zwykłą komórkę. Tabeli nie można powiększyć
ponad 50 wierszy na 20 kolumn; zaimportowana tabela większa niż ten limit
pozostaje w pełni zapisywalna, dopóki nie spróbujesz powiększyć jej jeszcze
bardziej, ale zmniejszenie jej poniżej limitu jest jednokierunkowe. Nie
przyznaje punktów i niczego nie odsłania.

## {el:spoiler} Rozwijana treść

Blok, który ukrywa swoją zawartość za kliknięciem, wykorzystując
natywny przełącznik `<details>` bez JavaScriptu. Użyj go, aby schować podpowiedź,
rozwiązanie zadania lub dygresję, którą uczeń otworzy, gdy zechce. Ustaw
opcjonalny **Tekst przycisku** (domyślnie *Pokaż*) i wpisz ukrytą treść
tym samym paskiem narzędzi tekstu sformatowanego (pogrubienie/kursywa/
podkreślenie, nagłówki, listy, linki, cytat, kod, wyrównanie) co w innych
polach tekstowych.

## {el:stepper} Krok po kroku

Uporządkowana lista krótkich **Kroków** — po jednej linii tekstu lub wzoru
w linii każdy (np. `\(2^{10}\)`) — z opcjonalnym **Wprowadzeniem** nad nimi.
Pierwszy krok jest widoczny od razu; przycisk "Pokaż dalej" odsłania
resztę pojedynczo. Element nieoceniany, bez zapamiętywania stanu —
odświeżenie strony zaczyna przechodzenie od pierwszego kroku od nowa.

## {el:markdone} Lista zadań

Opcjonalne polecenie oraz uporządkowany zestaw krótkich **pozycji listy**,
które uczeń odhacza, zapisując "to zrobiłem" — do listy do nauki lub zadań
realizowanych we własnym tempie, a nie do pytania z jedną poprawną
odpowiedzią. W odróżnieniu od pozostałych elementów
interaktywnych, odhaczenia ucznia zapisują się między jego kolejnymi
wizytami. Element nieoceniany.

## {el:guessnumber} Zgadnij liczbę

Element samosprawdzający z odpowiedzią liczbową, dający informację
kierunkową zamiast zwykłego werdyktu dobrze/źle. Zapisz sformatowaną
**Treść z odpowiedzią**, oznaczając cel jako `{{42}}` (dokładnie raz),
opcjonalną **Tolerancję (±)** oraz sformatowany **Komunikat po poprawnej
odpowiedzi** wyświetlany, gdy odpowiedź mieści się w tolerancji — pamiętaj,
że jest on widoczny w źródle strony, więc nie umieszczaj w nim niczego
poufnego. Błędna odpowiedź otrzymuje jedynie informację "za duża" lub "za
mała" i można próbować bez ograniczeń; element nie przyznaje punktów i
niczego nie odsłania, bo jego sens polega na tym, by uczeń mógł się mylić
wielokrotnie, zawężając poszukiwania.

## Zobacz też

- [Edytory treści](content-editors) — typy bloków treści oraz sposób, w
  jaki Zakładki/Kolumny zagnieżdżają te elementy interaktywne obok nich.
- [Edytory quizów](quiz-editors) — elementy pytań, oceniany/punktowany
  odpowiednik używany zarówno do ćwiczeń w lekcji, jak i punktacji w quizie.
