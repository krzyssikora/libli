# Eksport i import kursu

libli potrafi spakować cały kurs — lub pojedynczy jego fragment — do
archiwum `.zip`, a następnie wczytać takie archiwum z powrotem, jako
zupełnie nowy kurs albo jako treść dołączoną do już istniejącego.

## Eksport

W **kreatorze** kursu użyj przycisku **Eksportuj kurs**, aby pobrać cały
kurs, albo **Eksportuj** przy dowolnym węźle (części, rozdziale, sekcji lub
jednostce), aby pobrać tylko ten fragment. Archiwum zawiera pełną
strukturę, całą treść lekcji i quizów oraz powiązane materiały.

Jeśli część powiązanych materiałów nie może zostać spakowana (na przykład
plik, który został wcześniej usunięty z magazynu), eksport nie kończy się
od razu błędem: trafiasz na **stronę wstępną** wypisującą napotkane
problemy i możesz zdecydować, czy kontynuować — brakujące materiały
zostaną zastąpione w wyeksportowanej treści wyraźnie oznaczonym zastępczym
elementem — czy anulować i najpierw naprawić źródło.

## Import

Użyj **Zarządzaj → Kursy → Import**, aby wczytać plik `.zip` i utworzyć z
niego nowy kurs, albo **Import** wewnątrz kreatora danego kursu, aby wstawić
fragment do tego kursu w wybranym miejscu. W obu przypadkach przebieg jest
taki sam:

1. **Wczytanie** archiwum. Zostaje ono zwalidowane i tymczasowo
   zapamiętane, ale jeszcze nie zastosowane.
2. **Podgląd** — przeglądasz, co zostanie utworzone, w tym gdzie zostanie
   wstawiony fragment (proponowane są wyłącznie strukturalnie poprawne
   miejsca wstawienia).
3. **Potwierdzenie**, aby zastosować import, lub **Anulowanie**, aby
   odrzucić tymczasowo zapamiętane archiwum.

Tymczasowo zapamiętane archiwum wygasa po pewnym czasie; jeśli wrócisz do
nieaktualnego podglądu, wczytaj archiwum ponownie. Bardzo duże archiwa są
odrzucane od razu, na podstawie skonfigurowanego dla tej instancji limitu
rozmiaru, a nie dopiero w trakcie przesyłania.

## Kiedy czego użyć

- Przenoszenie kursu między środowiskami (np. staging → produkcja):
  wyeksportuj cały kurs i zaimportuj go jako nowy w środowisku docelowym.
  Zobacz [Zakładanie kursu](create-a-course), by sprawdzić, które pola
  świeżo zaimportowanego kursu nadal można edytować.
- Ponowne wykorzystanie rozdziału lub jednostki w innym kursie: wyeksportuj
  tylko ten fragment i zaimportuj go w kreatorze kursu docelowego.
