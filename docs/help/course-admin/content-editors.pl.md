# Edytory treści

Jednostka typu **lekcja** to sekwencja elementów treści — tekstu, mediów i
osadzeń — które uczniowie czytają od góry do dołu. Otwórz lekcję z poziomu
kreatora, aby przejść do jej **edytora** — ekranu dwupanelowego (Edytor i
podgląd na żywo, z przełącznikiem widoku Edytor/Podział/Podgląd). Panel
edytora wyświetla konspekt jej elementów w kolejności, a jego przycisk
**Dodaj element** otwiera menu typów; na najwyższym poziomie lekcji pokazuje
ono cztery grupy — Treść, Interaktywne, Pytania i Struktura (grupa
Interaktywne jest niedostępna w quizie). Grupę Pytania opisuje
[Edytory quizów](quiz-editors).

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

## Zobacz też

- [Edytory quizów](quiz-editors) — typy elementów pytań, używane zarówno w
  lekcjach (jako ćwiczenie), jak i w quizach (jako ocena).
- [Menedżer mediów](media-manager) — przesyłanie i porządkowanie obrazów oraz
  filmów.
- [Tworzenie kursu](builder) — gdzie jednostki znajdują się w strukturze
  kursu.
