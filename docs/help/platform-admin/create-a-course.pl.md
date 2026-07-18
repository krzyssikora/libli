# Zakładanie kursu

Aby założyć kurs, otwórz **Studio** i kliknij **Nowy kurs**. Formularz na
tej stronie tworzy szkielet kursu; treścią wypełniasz go później w kreatorze.

![Lista kursów w Studio](static:core/img/help/course-list.pl.png)

## Pola podstawowe

![Formularz tworzenia kursu](static:core/img/help/course-create.pl.png)

- **Tytuł** — widoczny w całej platformie oraz w katalogu.
- **końcówka URL (slug)** *(opcjonalne)* — fragment adresu URL; pozostaw
  puste pole, a zostanie wygenerowany z tytułu, z liczbowym sufiksem, jeśli
  dany slug jest już zajęty.
- **Struktura** — jeden z czterech presetów (**Płaska**, **Rozdziały**,
  **Części**, **Pełna**), który decyduje, z jakich poziomów treści korzysta
  kurs. Wybierz najprostszy pasujący preset; możesz go później pogłębić bez
  utraty istniejących jednostek, ale nie możesz później usunąć poziomu,
  który zawiera już treść.

## Przedmioty i widoczność

Zaznacz jeden lub więcej **Przedmiotów**, aby umieścić kurs w taksonomii
używanej przez katalog i filtry analityczne — jeśli potrzebnego przedmiotu
jeszcze nie ma, zobacz [Przedmioty](subjects). **Widoczność** decyduje o
tym, w jaki sposób uczniowie trafiają do kursu: kursy **Otwarte** pojawiają
się w katalogu uczniowskim do samodzielnego zapisu (opcjonalnie ograniczone
do wybranych kohort w polu **Kto może się zapisać**), natomiast kursy
**Przypisane** są dostępne wyłącznie poprzez zapis przez nauczyciela/
administratora lub grupę.

## Właściciel (administrator kursu)

Pole **Właściciel** przypisuje administratora kursu — osobę, która na co
dzień buduje i edytuje ten kurs. Jako administrator platformy możesz ustawić
tu siebie lub dowolnego administratora kursu; jeśli pozostawisz je puste
przy tworzeniu, domyślnie trafi do Ciebie. Właściciela możesz później zmienić
z poziomu formularza edycji kursu.

## Kod synchronizacji ocen

Jeśli wyniki tego kursu mają trafiać do Twojego systemu informacji o szkole
(SIS), ustaw **Kod przedmiotu w rejestrze zewnętrznym** na kod przedmiotu,
którego oczekuje Twój SIS/e-dziennik. Pozostaw pole puste, aby całkowicie
wyłączyć ten kurs z synchronizacji ocen — zobacz [Integracje (synchronizacja
ocen)](integrations).

## Po utworzeniu

Zapisanie formularza przenosi od razu do **kreatora**, gdzie dodajesz
rozdziały, lekcje i quizy. Treść możesz przenosić do i z kursu w dowolnym
momencie — zobacz [Eksport i import kursu](export-import).
