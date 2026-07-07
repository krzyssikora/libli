# Kohorty

**Kohorta** to grupowanie uczniów obejmujące całą platformę, niezależne od
konkretnego kursu — zwykle rocznik lub nabór. Zarządzaj kohortami z
**Zarządzaj → Kohorty** (tylko Administrator Platformy; Administratorzy
Kursu widzą nazwy kohort przy wybieraniu uczniów do grupy, ale nie mają
dostępu do tej listy).

## Kohorta domyślna

Każdy uczeń, który nie został inaczej przypisany, należy do kohorty
**Domyślnej**. Nie można jej usunąć ani zarchiwizować, a jej slug jest na
stałe zarezerwowany — dowolną kohortę można przemianować, ale nic innego
nie może przejąć nazwy „Domyślna” jako swojej tożsamości.

## Tworzenie i archiwizowanie kohort

Użyj **Dodaj kohortę**, aby utworzyć nową z nazwą (jej slug jest
generowany, a następnie zamrażany — adresy URL kohorty pozostają stabilne
nawet po zmianie nazwy). **Archiwizuj** wycofuje kohortę, do której nie
przypisujesz już uczniów, bez usuwania jej historii; zarchiwizowaną
kohortę można przywrócić tym samym przyciskiem. **Ustaw jako domyślną**
czyni inną kohortę nową kohortą Domyślną. Kohortę można usunąć dopiero,
gdy nie ma już żadnych członków.

## Przypisywanie uczniów

Otwórz kohortę, aby zobaczyć jej członków i dodać do niej uczniów z listy
tych, którzy jeszcze do niej nie należą. Uczeń w danym momencie należy do
dokładnie jednej kohorty — dodanie go do nowej automatycznie usuwa go z
poprzedniej.

## Gdzie kohorty mają znaczenie

Poza grupowaniem uczniów na własny użytek, kohorty mogą ograniczać
samodzielny zapis na kurs: kurs **Otwarty** może być ograniczony do
wybranych **Kohort z samodzielnym zapisem** — zobacz [Zakładanie
kursu](create-a-course) — dzięki czemu widzą go w katalogu wyłącznie
uczniowie z tych kohort.
