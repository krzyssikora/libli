# Kohorty

**Kohorta** to grupowanie uczniów obejmujące całą platformę, niezależne od
konkretnego kursu — zwykle rocznik lub nabór. Zarządzaj kohortami z
**Administracja → Kohorty** (tylko administrator platformy; administratorzy
kursu widzą nazwy kohort przy wybieraniu uczniów do grupy, ale nie mają
dostępu do tej listy).

## Kohorta domyślna

Każdy uczeń, który nie został inaczej przypisany, należy do kohorty
**Default** (na liście widoczna jako **Default (domyślna)** — to
przechowywana nazwa jest angielskim „Default”, tłumaczony jest tylko
dopisek w nawiasie). Nie można jej usunąć ani zarchiwizować, a jej slug
jest na stałe zarezerwowany — dowolną kohortę można przemianować, ale nic
innego nie może przejąć nazwy „Default” jako swojej tożsamości.

## Tworzenie i archiwizowanie kohort

Użyj **Nowa kohorta**, aby utworzyć nową z nazwą (jej slug jest
generowany, a następnie zamrażany — adresy URL kohorty pozostają stabilne
nawet po zmianie nazwy). **Archiwizuj** wycofuje kohortę, do której nie
przypisujesz już uczniów — i przenosi jej obecnych członków do kohorty
Default, więc zarchiwizowana kohorta jest zawsze pusta, gdy później
użyjesz **Przywróć z archiwum**. **Ustaw jako domyślną** czyni inną
kohortę nową kohortą Default (ustawienie zarchiwizowanej kohorty jako
domyślnej automatycznie przywraca ją z archiwum). **Usuń** działa tak
samo jak **Archiwizuj**: najpierw przenosi pozostałych członków do
kohorty Default, a dopiero potem usuwa kohortę — nie ma minimalnego
wymogu co do liczby członków ani potrzeby wcześniejszego jej
opróżniania.

## Przypisywanie uczniów

Otwórz kohortę, aby zobaczyć jej członków i dodać do niej uczniów z listy
tych, którzy jeszcze do niej nie należą. Uczeń w danym momencie należy do
dokładnie jednej kohorty — dodanie go do nowej automatycznie usuwa go z
poprzedniej.

## Gdzie kohorty mają znaczenie

Poza grupowaniem uczniów na własny użytek, kohorty mogą ograniczać
samodzielny zapis na kurs: kurs **Otwarty** może być ograniczony do
wybranych kohort w polu **Kto może się zapisać** — zobacz [Zakładanie
kursu](create-a-course) — dzięki czemu widzą go w katalogu wyłącznie
uczniowie z tych kohort.
