# Edytory quizów

Elementy pytań działają tak samo w jednostce **quiz** (ocenianej, punktowanej)
i w jednostce **lekcja** (ćwiczeniowej, nieocenianej) — dodajesz i edytujesz je
z edytora jednostki dokładnie tak samo jak [elementy treści](content-editors),
przez **Dodaj element** (grupa **Pytania**). Każde pytanie ma dwa wspólne
pola:

- **Treść pytania** — polecenie (tekst sformatowany, obsługuje wzory w
  linii). Wyświetlana nazwa pola różni się w zależności od typu:
  **Pytanie**, **Polecenie (opcjonalne)** lub **Zdanie z lukami**.
- **Wyjaśnienie (opcjonalne)** — tekst informacji zwrotnej pokazywany po
  udzieleniu odpowiedzi.

W **quizie** pojawiają się dodatkowo trzy pola — edytor lekcji w ogóle ich
nie renderuje:

- **Tryb oceniania** — Automatycznie oceniane (punktowane automatycznie),
  Wymaga recenzji (ocenia je później człowiek — zobacz kolejkę
  weryfikacji) lub Nieoceniane (zapisywane, ale nigdy nie punktowane).
- **Maks. prób** i **Maks. punktów** — ile podejść ma uczeń i ile punktów
  warta jest poprawna odpowiedź.

Poniższe pola specyficzne dla typu decydują o tym, czym różni się zachowanie
poszczególnych rodzajów pytań.

## Jednokrotny wybór / Wielokrotny wybór

Lista **odpowiedzi**, z których każda jest oznaczona jako poprawna lub
niepoprawna. Wybór jednokrotny renderuje się jako przyciski radiowe
(dokładnie jedna odpowiedź); wybór wielokrotny — jako checkboxy (dowolna
kombinacja). Ocenianie jest ścisłe: przy wyborze wielokrotnym uczeń musi
zaznaczyć *wszystkie* poprawne odpowiedzi i *żadnej* niepoprawnej, aby
otrzymać punkty — częściowe zaznaczenia dają zero punktów.

Każda odpowiedź może też mieć opcjonalną informację zwrotną dla tej opcji
(**feedback**). Jak ujmuje to podpowiedź w edytorze: "Opcjonalna informacja
zwrotna pojawia się, gdy uczeń pomyli się na opcji — wybierze złą albo
pominie poprawną." Pozostaw pole puste, aby zrezygnować z informacji
zwrotnej dla danej odpowiedzi.

To zmienia, co pokazuje niepoprawna odpowiedź, i zależy od typu jednostki:

- W **lekcji**, bez informacji zwrotnej dla opcji, niepoprawna odpowiedź
  pokazuje tylko werdykt (Poprawnie/Niepoprawnie) — poprawna odpowiedź nigdy
  nie jest ujawniana. Z informacją zwrotną dla opcji, odpowiedzi, w których
  uczeń się pomylił (zła odpowiedź wybrana albo poprawna pominięta), są
  oznaczane w treści pytania i pokazują swój tekst informacji zwrotnej — ale
  tylko te oznaczone odpowiedzi; nie ma osobnej listy poprawnych odpowiedzi.
- W **quizie** poprawne odpowiedzi są zawsze ujawniane, gdy uczeń wyczerpie
  liczbę prób (przy ostatniej niepoprawnej próbie albo później, w wynikach/
  przeglądzie) — niezależnie od tego, czy którakolwiek odpowiedź ma tekst
  informacji zwrotnej.

## Krótki tekst

Jednowierszowa odpowiedź w formie wolnego tekstu, oceniana przez porównanie
odpowiedzi ucznia z listą **odpowiedzi akceptowanych** (po jednej w wierszu —
dodaj każdy wariant pisowni/sformułowania, który chcesz zaakceptować).
Włącz opcję **rozróżniaj wielkość liter**, jeśli wielkość liter musi się
zgadzać dokładnie; domyślnie porównanie ignoruje wielkość liter i skrajne
białe znaki.

## Liczba

Odpowiedź liczbowa, uznawana za poprawną, jeśli mieści się w zadanej
**tolerancji** od docelowej **wartości** (tolerancja 0 oznacza dopasowanie
dokładne). Użyj tego typu dla odpowiedzi obliczeniowych, gdy chcesz
akceptować niewielkie różnice zaokrągleń.

## Uzupełnij luki

Treść pytania z jedną lub kilkoma lukami wewnątrz tekstu. Zapisz treść,
oznaczając każdą lukę jako `{{odpowiedź}}`, używając `|` do oddzielenia
akceptowanych wariantów, np. `Stolicą Francji jest {{Paryż|paryż}}.` —
edytor zamienia każdy taki znacznik w osobną lukę z własną listą
akceptowanych odpowiedzi, a każda luka jest oceniana niezależnie.

## Przeciągnij słowa

Podobnie jak w pytaniach typu Uzupełnij luki, ale uczeń przeciąga fiszki ze
słowami do luk zamiast je wpisywać. Oznacz każdą lukę tak samo, wpisując
`{{token}}` w treści; dodaj opcjonalne **dystraktory** (dodatkowe błędne
fiszki wyświetlane obok poprawnych), aby utrudnić zgadywanie.

## Dopasuj pary

Pytanie typu dopasowanie dwóch kolumn: lista etykiet **lewych** (stałe cele)
z przypisanym poprawnym **prawym** tokenem (odpowiedzią do przeciągnięcia
lub wybrania). Dodaj opcjonalne **dystraktory** — dodatkowe tokeny prawej
strony bez odpowiadającej im etykiety po lewej — aby uniemożliwić
odgadywanie przez eliminację.

## Pytanie macierzowe

Siatka **stwierdzeń** (wierszy) w zestawieniu ze wspólnym zbiorem
**kolumn** (opcji odpowiedzi) — każde stwierdzenie jest oceniane przez
wybór dokładnie jednej poprawnej kolumny. Dodawaj kolumny dowolnie, albo
kliknij **Szablon Prawda/Fałsz**, aby od razu utworzyć te dwie kolumny.
Każdy wiersz jest oceniany niezależnie (częściowe punkty), inaczej niż
przy ścisłym, zero-jedynkowym ocenianiu opisanym wyżej.

## Siatka wielokrotnego wyboru

Podobnie jak Pytanie macierzowe — ta sama siatka **stwierdzeń** w
zestawieniu z **kolumnami** — ale każde stwierdzenie może mieć *kilka*
poprawnych kolumn: zaznacz każdą kolumnę, która pasuje w danym wierszu.
Ocenianie jest zero-jedynkowe dla każdego wiersza: stwierdzenie liczy się
jako poprawne tylko wtedy, gdy cały zestaw zaznaczonych kolumn się zgadza.

## Przeciągnij na obraz

Uczeń przeciąga etykiety na oznaczone strefy na zdjęciu. Wybierz obraz z
biblioteki mediów, a następnie użyj **edytora stref**: przeciągnij kursorem
bezpośrednio po obrazie, aby narysować prostokątną strefę, i wpisz jej
poprawną etykietę. Kliknij istniejącą strefę (lub jej wiersz), aby ją
zaznaczyć, zmienić rozmiar uchwytami lub usunąć. Dodaj opcjonalne etykiety
**dystraktorów** w ten sam sposób, co w pozostałych typach przeciągania.

## Rozszerzona odpowiedź

Długa odpowiedź w formie wolnego tekstu (na długość eseju). Może być
oceniana automatycznie na podstawie list słów kluczowych **wymaganych** i
**zabronionych** (po jednym w wierszu), albo ustawiona jako **Wymaga
recenzji**, tak aby nauczyciel przeczytał ją i ocenił ręcznie później,
albo jako **Nieoceniane**, jeśli chcesz jedynie zbierać odpowiedzi bez ich
oceniania.

## Gdzie znajdują się pytania

Te same typy pytań działają w obu kontekstach:

- W **lekcji** uczniowie mogą od razu sprawdzić swoją odpowiedź i zobaczyć
  informację zwrotną — przydatne do ćwiczeń.
- W **quizie** odpowiedzi są zbierane i oceniane (lub kierowane do
  weryfikacji) w ramach ocenianego podejścia; zobacz instrukcję dotyczącą
  analityki, aby dowiedzieć się, jak wyniki są potem prezentowane.

Lekcje oferują też zestaw widżetów samosprawdzających dostępnych tylko w
lekcjach, nieocenianych — zobacz [Elementy interaktywne](interactive-elements)
po rodzinę "Pokaż więcej"/"Uzupełnij i potwierdź"/"Wybierz i zatwierdź" oraz
ich odpowiedniki, ćwiczeniowy odpowiednik pytań-jako-praktyki.

## Zobacz też

- [Edytory treści](content-editors) — typy bloków niebędących pytaniami.
- [Menedżer mediów](media-manager) — przesyłanie obrazów używanych w
  pytaniach typu Przeciągnij na obraz.
- [Tworzenie kursu](builder) — tworzenie jednostek typu lekcja i quiz.
