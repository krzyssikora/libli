# libli dla szkół

## Co oferujemy

- platforma do tworzenia kursów z urozmaiconymi i interaktywnymi treściami edukacyjnymi
- każdy kurs może dzielić się na części, rozdziały, sekcje etc. Na dole takiego podziału są
  lekcje lub testy
- około trzydziestu rodzajów elementów treści: tekst, obrazy, wideo, tabele, galerie, panele z
  zakładkami, wyróżnienia, układy wielokolumnowe, rozwijana treść, notacja matematyczna
  składana w LaTeX-u oraz liczne elementy interaktywne, takie jak przeciąganie na obraz,
  uzupełnianie luk, dobieranie par, siatki odpowiedzi, osadzone arkusze GeoGebry lub innych
  obiektów typu "iframe"
- testy z automatycznym sprawdzaniem: pytania o ustalonej odpowiedzi są sprawdzane w chwili
  przesłania. Odpowiedzi otwarte trafiają do kolejki, w której czyta je i ocenia edukator. Przy
  większej liczbie dozwolonych prób każda próba jest zapisywana, nie tylko ostatnia
- analityka dla edukatorów: macierz postępów i wyników dla grupy, szczegółowe wyniki każdego
  ucznia, szczegóły każdego testu, a także eksport wyników
- interfejs po polsku lub angielsku, zgodnie z wyborem użytkownika

## Wypróbuj wersję demonstracyjną

Możemy przygotować dla Twojej szkoły prywatne demo: konto nauczyciela i konto ucznia w naszym
kursie licealnej matematyki, razem z przykładową klasą, której wyniki pozwalają zobaczyć
analitykę w działaniu. Konto ucznia z tej klasy jest kontem „startowym” — bez żadnych postępów.
Dane o jego postępach pojawiają się w miarę przechodzenia przez lekcje i testy, więc od razu
widać, jak zmienia się widok nauczyciela. Dostęp jest ważny przez dwa tygodnie.

Chcesz spróbować? Kontakt: {libli:contact_email}.

## Czego od Ciebie potrzebujemy

Jeśli chcesz używać libli pod adresem twoja_subdomena.libli.pl — nie potrzebujemy od Ciebie
nic. Po podpisaniu umowy przystępujemy do działania.

Jeśli chcesz używać libli pod własnym adresem (np. libli.twoja_domena.pl), potrzebujemy od
Ciebie trzech rekordów DNS: rekordu **A** kierującego Twoją domenę na serwer oraz rekordów
**SPF** i **DKIM**, dzięki którym poczta wysyłana w imieniu szkoły nie trafia do spamu. O
wszystkie trzy prosimy w jednym mailu, do tej samej osoby, która zarządza domeną. Zwykle da się
je ustawić tego samego dnia.

### Dwie pułapki w DNS, o których warto wiedzieć

Obie dotyczą wyłącznie własnej domeny — na poddomenie twoja_subdomena.libli.pl rekordami
**CAA** i **AAAA** zarządzamy sami, więc żadna z tych pułapek nie może wystąpić.

1. Rekord **CAA**, który pomija `letsencrypt.org`.

    Większość szkolnych domen w ogóle nie ma rekordu CAA — wtedy nie trzeba nic robić. Jeśli
    Twoja domena go ma, ale pomija `letsencrypt.org`, serwer nie uzyska certyfikatu i strona
    nigdy nie wystartuje przez HTTPS.

2. Nieaktualny rekord **AAAA**.

    Stary adres IPv6 pozostały po poprzedniej stronie kieruje część odwiedzających w złe
    miejsce, a problem ujawnia się tylko w sieciach, które obsługują IPv6. Usuń go przy okazji
    zmiany DNS opisanej wyżej.

## Czego nie potrzebujemy

Żadnego serwera. Żadnego sprzętu. Żadnych procedur zakupowych. Żadnego oprogramowania
instalowanego na urządzeniu ucznia — wystarczy przeglądarka. Opcjonalnie można też zainstalować
aplikację.

## Gdzie są dane

Dane Twojej szkoły będą przechowywane na jej odrębnym serwerze (nie dzielonym z innymi
instytucjami), umiejscowionym na terenie Unii Europejskiej, w zgodzie z europejskim prawem.
Jeden serwer na szkołę, nigdy współdzielony z danymi innej szkoły.

### Kopie zapasowe

Serwer jest co noc kopiowany na zaszyfrowany nośnik, także na terenie Unii Europejskiej.
Kopię nocną przechowujemy **30 dni**, a jedną kopię miesięczną przez kolejne **12 miesięcy**.
Pliki usunięte z kursu pozostają w kopii **90 dni**, aby można było cofnąć przypadkowe
usunięcie. Po tym czasie również są usuwane.

## Co się dzieje, gdy odchodzisz

Możesz zrezygnować w dowolnym momencie i zabrać swoje dane ze sobą. Przekazanie danych działa
jako **rotacja klucza**: to Ty generujesz nowy klucz szyfrujący, na własnym urządzeniu, i
przekazujesz nam tylko jego **część publiczną** — część prywatna nigdy nie opuszcza Twoich rąk.
Tym kluczem publicznym ponownie szyfrujemy aktualną kopię zapasową i przekazujemy Ci gotowe
archiwum. Nigdy nie ujawniamy współdzielonego klucza, który chroni kopie zapasowe innych szkół,
i nigdy nie mamy dostępu do Twojego klucza prywatnego.

Jeśli zdecydujesz się później wrócić do libli, zadziała ten sam proces przywracania serwera do
stanu, w jakim został zarchiwizowany.

## Harmonogram

Po zmianie DNS opisanej wyżej Twoja strona może ruszyć jeszcze tego samego dnia.

Istnieje jedno znane nam ograniczenie. Jeśli szkoła chce korzystać z Microsoft Exchange Direct
Send, może to zrobić przez port, który jest domyślnie blokowany przez operatora serwera. Port
jest odblokowywany tylko dla stabilnego, płacącego konta — w praktyce takiego, które istnieje od
co najmniej 30 dni i ma co najmniej jedną rozliczoną fakturę. Odblokowanie jest bezpłatne; daj
nam znać wcześniej, jeśli wiesz, że będzie to potrzebne.

## Plany

Przy podpisaniu umowy rozmawiamy o pięciu wartościach:

- maksymalnej liczbie uczniów na platformie,
- liczbie planowanych kursów,
- szacunkowej liczbie filmów na kurs,
- typowej długości filmu,
- oraz o liczbie osób tworzących treści.

{libli:pricing_plans}

{libli:vat_note}
