# Zarządzanie listą uczniów

Listę grupy — jej uczniów i nauczycieli — nauczyciel zawsze może
**zobaczyć**: otwarcie grupy z **Moje grupy** prowadzi do strony tylko do
odczytu, na której widnieją wszyscy jej członkowie — tej samej listy, na
której opiera się analityka i sprawdzanie quizów dla tej grupy. Edytowanie
jej — dodawanie czy usuwanie kogokolwiek — nie należy do nauczyciela: to
zadanie administratora kursu, wykonywane bezpośrednio w formularzu edycji
grupy. Nie ma osobnego przycisku **Edytuj**; na zakładce **Zarządzaj** samą
**nazwę** grupy stanowi odnośnik do edycji, a wiersz poza tym udostępnia
tylko **Archiwizuj**/**Przywróć z archiwum** oraz **Usuń**, a nową grupę
administrator kursu zakłada tam przyciskiem **Nowa grupa**. Strona, na którą
trafia się z **Moje grupy**, nie ma żadnej opcji edycji.

Reszta tego tematu opisuje, jak administrator kursu buduje taką listę —
warto to wiedzieć, bo tłumaczy to, co widzisz na swoim widoku tylko do
odczytu.

## Wybieranie uczniów

Wybór uczniów, który wypełnia administrator kursu, to lista pól wyboru — ale
nie jest ona ograniczona do kursu grupy: obejmuje **każdego użytkownika
platformy niebędącego personelem**, a kurs nigdy nie jest brany pod uwagę.
Dwa filtry zawężają tylko *widok*, nie samą listę:

- **Kohorta** — lista rozwijana z opcją *Wszystkie kohorty* oraz każdą
  kohortą z nazwy. Wybranie jednej zawęża listę do danego naboru.
- **Szukaj wg nazwiska** — pole tekstowe dopasowujące dowolną część nazwiska,
  bez rozróżniania wielkości liter, w miarę pisania.

Licznik na żywo pokazuje **widoczne / łącznie** podczas filtrowania, więc
zawsze wiadomo, jak dużą część listy ukrywa filtr. Osobny licznik
**Dodano: N** śledzi bieżący wybór, ze wskazówką **(zapisano: N)**, gdy
różni się on od ostatnio zapisanego stanu — to przypomnienie o
niezapisanych zmianach.

## Dodawanie i usuwanie

Zaznaczenie ucznia dodaje go; odznaczenie usuwa. Zapisanie zatwierdza
zmianę: każdy uczeń pozostawiony bez zaznaczenia zostaje usunięty z grupy.
Filtrowanie nigdy nie gubi zaznaczenia — każde pole wyboru pozostaje na
stronie przez cały czas, więc uczeń zaznaczony przy jednym filtrze wciąż
zostaje zapisany, nawet jeśli późniejszy filtr go ukryje.

Wybór nauczycieli działa tak samo, tylko z wyszukiwaniem po nazwisku.

## Kohorty przydziela się gdzie indziej

Przenoszenie ucznia *między* kohortami to również osobna czynność i też nie
odbywa się tutaj: wykonuje ją administrator platformy na stronie edycji danej
kohorty, wybierając uczniów z listy pól wyboru podpisanej „Przypisz uczniów
do tej kohorty (przeniesie ich z obecnej kohorty)” i zatwierdzając
przyciskiem **Przypisz**. Filtr kohorty na tej stronie jedynie *filtruje*
listę — nigdy nie zmienia, do której kohorty należy uczeń.

## Powiązane tematy

- [Grupy i kolekcje](groups-collections)
- [Macierz analityczna](analytics)
- [Sprawdzanie quizów](quiz-review)
