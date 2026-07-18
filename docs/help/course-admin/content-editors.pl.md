# Edytory treści

Jednostka typu **lekcja** to sekwencja elementów treści — tekstu, mediów i
osadzeń — które uczniowie czytają od góry do dołu. Otwórz lekcję z poziomu
kreatora, aby przejść do jej **edytora** — ekranu dwupanelowego (Edytor i
podgląd na żywo, z przełącznikiem widoku Edytor/Podział/Podgląd). Panel
edytora wyświetla konspekt jej elementów w kolejności, a jego przycisk
**Dodaj element** otwiera menu typów; na najwyższym poziomie lekcji pokazuje
ono cztery grupy — Treść, Interaktywne, Pytania i Struktura (grupa
Interaktywne jest niedostępna w quizie). Grupę Pytania opisuje
[Edytory quizów](quiz-editors). Grupę Interaktywne opisuje
[Elementy interaktywne](interactive-elements).

![Edytor lekcji z blokami treści](static:core/img/help/content-editor.pl.png)

## Praca z elementami

Każdy element jest dodawany, edytowany i zapisywany niezależnie:

- Kliknij **Dodaj element** i wybierz kartę typu, aby wstawić nowy element
  na końcu jednostki.
- Kliknij istniejący element w konspekcie, aby otworzyć jego formularz
  edycji w miejscu.
- Przeciągaj elementy w konspekcie, aby zmienić ich kolejność; kolejność
  odczytu aktualizuje się natychmiast.
- Usuń element przyciskiem 🗑 w jego wierszu; jego formularz edycji oferuje
  tylko przyciski **Zapisz** i **Anuluj**.

Każdy element ma też opcjonalne pole **Etykieta (opcjonalnie)** (podpowiedź
*Wyświetlana na liście elementów*) — służy wyłącznie do oznaczenia go w
konspekcie; uczniowie nigdy go nie widzą.

## Typy elementów treści

**Tekst** — podstawowy blok. Pole tekstu sformatowanego obsługujące
nagłówki, listy, pogrubienie/kursywę, linki oraz wzory matematyczne wpisane
w liniowym tekście za pomocą znaczników KaTeX (np. `$x^2$`). Używaj go do
wyjaśnień, instrukcji i dowolnej treści między innymi elementami.

**Obraz** — osadza zdjęcie z biblioteki mediów kursu. Wybierz istniejący
plik lub prześlij nowy od razu (zobacz [Menedżer mediów](media-manager));
dodaj opcjonalny **tekst alternatywny** dla dostępności (pozostaw go pusty
tylko dla obrazu czysto dekoracyjnego) oraz opcjonalny **podpis** wyświetlany
pod obrazem.

**Wideo** — osadza film na dwa sposoby: wybierz przesłany plik wideo z
biblioteki mediów *albo* wklej link do filmu hostowanego (YouTube, Vimeo i
podobne są automatycznie normalizowane do postaci osadzalnej). Podaj
dokładnie jedną z tych dwóch opcji — nie obie naraz i nie żadną.

**Iframe** — osadza dowolną zewnętrzną stronę interaktywną poprzez
wklejenie jej linku udostępniania lub pełnego fragmentu `<iframe>`,
najczęściej apletu GeoGebry. Wklejenie linku GeoGebry jest automatycznie
sprowadzane do widoku samego arkusza roboczego, a osadzenie zachowuje
oryginalne proporcje, jeśli źródło podało szerokość/wysokość. Nadaj mu
opisowy **tytuł** ze względu na dostępność. Osadzić można tylko domeny
dopuszczone przez administratora platformy.

**Wzór** — samodzielny blok wzoru w trybie wyświetlanym. Wpisz LaTeX;
jest renderowany po stronie klienta za pomocą KaTeX. Użyj tego bloku dla
wzoru, który zasługuje na własną linię, a nie dla krótkiego wyrażenia w
tekście — to lepiej umieścić wewnątrz elementu Tekst.

**HTML** — surowy HTML/CSS/JS dla autorów, którzy potrzebują czegoś, czego
pozostałe typy bloków nie potrafią (własny widżet, animacja, autorska
interakcja). Działa w izolowanej ramce oddzielonej od reszty strony, a
wspólny CSS/JS kursu (konfigurowany w ustawieniach kursu) jest dostępny dla
każdego bloku HTML w tym kursie. Używaj go oszczędnie — treść nie jest
sanityzowana, więc powinni z niego korzystać tylko zaufani autorzy, a
utrzymanie takiego bloku jest trudniejsze niż pozostałych typów.

**Tabela** — edytor siatki typu WYSIWYG: kliknij komórkę, aby edytować jej
tekst sformatowany (pogrubienie, kursywa, podkreślenie, wzory w linii oraz
wyrównanie poziome/pionowe) na miejscu, a uchwytami wierszy/kolumn wstawiaj
lub usuwaj wiersze i kolumny. Włącz **Wiersz nagłówkowy** i
**Kolumna nagłówkowa**, aby wyróżnić pierwszy wiersz/kolumnę, oraz wybierz
styl **Obramowanie** (**Siatka**, **Wiersze**, **Tylko nagłówek** albo
**Brak**).

**Galeria** — karuzela obrazów wyświetlanych pojedynczo, z nawigacją.
Kliknij **Dodaj obraz**, aby wybrać plik z biblioteki mediów, dodaj do
każdego obrazu opcjonalny opis w tekście sformatowanym oraz zmieniaj
kolejność lub usuwaj obrazy przyciskami w wierszu. **Pozycja opisu**
umieszcza podpis **Pod obrazem** lub **Nad obrazem**.

**Ramka** — zawsze widoczna, oprawiona wstawka na notatkę, która ma się
wyróżnić na tle otaczającego tekstu. Wybierz **Rodzaj** (Przykład, Notatka,
Wskazówka lub Uwaga — każdy z własnym kolorem akcentu i ikoną), opcjonalny
**Nagłówek** (jeśli pozostawiony pusty, używany jest domyślny nagłówek dla
danego rodzaju) oraz treść w tekście sformatowanym.

**Zakładki** — kontener dzielący swoją zawartość na nazwane zakładki, między
którymi przełącza się uczeń; dodawaj, usuwaj, zmieniaj kolejność i nazywaj
zakładki z listy wierszy w edytorze. Każda zakładka zawiera własne
zagnieżdżone elementy, dodawane z jej własnego menu **Dodaj element** —
zobacz „Kontenery i zagnieżdżanie” poniżej, co można w nich umieścić.

**Kolumny** — kontener układający swoją zawartość obok siebie w 2 do 4
kolumnach; ustaw **Liczba kolumn** i wypełnij każdą kolumnę z jej własnej
grupy na liście elementów pod edytorem. Zmniejszenie liczby kolumn zachowuje
kolumny z lewej strony i przenosi zawartość każdej usuniętej kolumny do
ostatniej pozostałej, zamiast ją kasować. Zobacz „Kontenery i zagnieżdżanie”
poniżej, co można w nich umieścić.

## Struktura

**Podział slajdów** — znacznik, a nie blok treści: nie ma żadnych pól i
sam w sobie nic nie wyświetla. Dodanie jednego lub więcej Podziałów slajdów
do lekcji zamienia ją w podzielony na slajdy widok pokazu slajdów zamiast
jednego długiego przewijanego widoku, a każdy podział rozpoczyna nowy slajd.
Podział na samym początku lub końcu, albo dwa podziały pod rząd, nigdy nie
tworzą pustego slajdu — są po prostu pomijane.

## Kontenery i zagnieżdżanie

Zakładki i Kolumny to dwa typy kontenerów. Wewnątrz każdego z nich
zagnieżdżone menu **Dodaj element** oferuje wyłącznie dziewięć niekontenerowych
typów treści — Tekst, Obraz, Wideo, Iframe, Wzór, HTML, Tabelę, Galerię,
Ramkę — oraz dziewięć samosprawdzających się elementów z grupy
[Elementy interaktywne](interactive-elements) (Pokaż więcej, Uzupełnij i
potwierdź, Wybierz i zatwierdź, Siatka przełączników, Tabela do uzupełnienia,
Rozwijana treść, Krok po kroku, Lista zadań, Zgadnij liczbę). Kontener nie
może zawierać innego kontenera, pytania ani Podziału slajdów — te pozostają
na najwyższym poziomie.

Elementy interaktywne są dostępne tylko w lekcjach: grupa Interaktywne w
ogóle nie pojawia się przy edycji quizu, więc w quizie menu dodawania
kontenera Zakładki lub Kolumny oferuje wyłącznie typy treści.

## Wskazówki

- Preferuj Tekst dla wszystkiego, co jest głównie prozą; sięgaj po
  Wzór lub HTML tylko wtedy, gdy potrzebujesz ich konkretnej
  możliwości.
- Wykorzystuj media ponownie: przesłanie tego samego zdjęcia dwa razy marnuje
  miejsce i zaśmieca bibliotekę — zamiast tego wybierz istniejący plik w
  selektorze mediów.
- Przed publikacją kursu podejrzyj jednostkę tak, jak zobaczy ją uczeń, aby
  wcześnie wychwycić problemy z układem (zbyt długie podpisy, zbyt duże
  ramki).

![Strona lekcji widziana przez uczniów](static:core/img/help/content-consume.pl.png)

## Zobacz też

- [Edytory quizów](quiz-editors) — typy elementów pytań, używane zarówno w
  lekcjach (jako ćwiczenie), jak i w quizach (jako ocena).
- [Elementy interaktywne](interactive-elements) — typy samosprawdzające
  dostępne tylko w lekcjach, zagnieżdżalne w Zakładkach i Kolumnach.
- [Menedżer mediów](media-manager) — przesyłanie i porządkowanie obrazów oraz
  filmów.
- [Tworzenie kursu](builder) — gdzie jednostki znajdują się w strukturze
  kursu.
