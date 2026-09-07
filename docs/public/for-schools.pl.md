# libli dla szkół

## Co otrzymujesz

Co platforma potrafi:

- **Kursy, lekcje i testy.** Kurs to drzewo rozdziałów i jednostek. Jednostka jest albo lekcją do
  przeczytania i przerobienia, albo testem, który się przesyła i który jest punktowany.
- **Około trzydziestu rodzajów elementów treści.** Tekst, obrazy, wideo, tabele, galerie, panele z
  zakładkami, wyróżnienia, układy dwukolumnowe, ukrywacze i bramki odsłaniające; notacja
  matematyczna składana w LaTeX-u; oraz elementy interaktywne — przeciąganie na obraz,
  uzupełnianie luk, dobieranie par, siatki odpowiedzi, kroczki, suwaki „przed i po”, osadzone
  arkusze GeoGebry.
- **Testy z automatycznym sprawdzaniem.** Pytania o ustalonej odpowiedzi są sprawdzane w chwili
  przesłania. Odpowiedzi otwarte trafiają do kolejki, w której czyta je i ocenia nauczyciel. Każda
  próba jest zapisywana, nie tylko ostatnia.
- **Analityka dla nauczyciela.** Macierz postępów i wyników dla grupy, z możliwością zejścia do
  jednego ucznia i jednego pytania, oraz eksport ocen.
- **Angielski i polski**, w interfejsie i w treści, przełączane osobno dla każdego użytkownika.

## Czego od Ciebie potrzebujemy

Trzy rekordy DNS, o które prosimy razem: rekord **A** kierujący Twoją domenę na serwer oraz
rekordy **SPF** i **DKIM**, dzięki którym poczta wysyłana w imieniu szkoły nie trafia do spamu. O
wszystkie trzy prosimy w jednym mailu, do tej samej osoby, która zarządza domeną, i zwykle da się
je ustawić tego samego dnia.

## Czego nie potrzebujemy

Żadnego serwera. Żadnego sprzętu. Żadnych procedur zakupowych. Żadnego oprogramowania
instalowanego na urządzeniu ucznia — wystarczy przeglądarka na tym, co uczeń już ma.

## Dwie pułapki w DNS, o których warto wiedzieć

**Rekord `CAA`, który pomija `letsencrypt.org`.** Większość szkolnych domen w ogóle nie ma rekordu
CAA — wtedy nie trzeba nic robić. Jeśli Twoja domena go ma i wymienia tylko inny urząd
certyfikacji, serwer nie może uzyskać certyfikatu i strona nigdy nie wystartuje przez HTTPS.

**Nieaktualny rekord `AAAA`.** Stary adres IPv6 pozostały po poprzedniej stronie kieruje część
odwiedzających w złe miejsce, a problem ujawnia się tylko w sieciach, które obsługują IPv6. Usuń
go przy okazji zmiany DNS opisanej wyżej.

## Gdzie są dane

Dane Twojej szkoły znajdują się na jej własnym serwerze u Hetznera, w Niemczech — jeden serwer na
szkołę, nigdy współdzielony z danymi innej szkoły.

**Kopie zapasowe.** Serwer jest co noc kopiowany na zaszyfrowany nośnik w Unii Europejskiej. Kopię nocną przechowujemy **30 dni**, a jedną kopię miesięczną przez kolejne **12 miesięcy**. Pliki usunięte z kursu pozostają w kopii **90 dni**, aby można było cofnąć przypadkowe usunięcie, i następnie również są usuwane.

## Co się dzieje, gdy odchodzisz

Możesz zrezygnować w dowolnym momencie i zabrać swoje dane ze sobą. Przekazanie danych działa jako
**rotacja klucza**: generujemy nowy klucz szyfrujący, uzgodniony tylko z Tobą, szyfrujemy nim
aktualną kopię zapasową i przekazujemy Ci ten klucz — nigdy klucza współdzielonego, który chroni
też kopie zapasowe innych szkół. Dalej działa ten sam proces, który przywraca serwer po awarii i
który stawia Twoje dane tam, gdzie zdecydujesz się je uruchomić.

## Harmonogram

Wyślij prośbę o zmiany DNS opisaną wyżej, a Twoja strona może działać jeszcze tego samego dnia.
Poczta wychodząca — resetowanie haseł, powiadomienia — jest wysyłana przez port 587, domyślny dla
każdej szkoły i port, którego Hetzner nigdy nie zablokował.

Szkoła, która koniecznie chce korzystać z Microsoft Exchange **Direct Send**, może to zrobić przez
port 25. Hetzner domyślnie blokuje ten port i odblokowuje go tylko dla ustabilizowanego,
płacącego konta — w praktyce takiego, które ma **30 dni** i co najmniej jedną rozliczoną fakturę.
Odblokowanie jest bezpłatne; daj nam znać wcześniej, jeśli wiesz, że będzie potrzebne.

## Plany

Przy podpisaniu umowy ustalamy pięć liczb: liczbę uczniów na platformie, liczbę planowanych
kursów, liczbę filmów na kurs, typową długość filmu oraz liczbę osób tworzących treści.

{libli:pricing_plans}

Ceny podawane są za rok szkolny.

{libli:vat_note}
