# libli dla szkół

## Co oferujemy

- platformę do tworzenia urozmaiconych i interaktywnych treści edukacyjnych tworzących kursy
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
- analityka dla edukatorów: macierz postępów i wyników dla grupy, z możliwością zejścia do
  jednego ucznia i jednego pytania, a także eksport wyników
- interfejs po polsku lub angielsku, zgodnie z wyborem użytkownika

## Czego od Ciebie potrzebujemy

Jeśli chcesz używać libli pod adresem twoja_subdomena.libli.pl — nie potrzebujemy od Ciebie
nic. Po podpisaniu umowy przystępujemy do działania.

Jeśli chcesz używać libli pod własnym adresem (np. libli.twoja_domena.pl), potrzebujemy od
Ciebie trzech rekordów DNS: rekordu **A** kierującego Twoją domenę na serwer oraz rekordy
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
instalowanego na urządzeniu ucznia — wystarczy przeglądarka na tym, co uczeń już ma.

## Gdzie są dane

Dane Twojej szkoły będą przechowywane na jej odrębnym serwerze (nie dzielonym z innymi
instytucjami), umiejscowionym na terenie Unii Europejskiej, w zgodzie z europejskim prawem.
Jeden serwer na szkołę, nigdy współdzielony z danymi innej szkoły.

**Kopie zapasowe.** Serwer jest co noc kopiowany na zaszyfrowany nośnik w Unii Europejskiej.
Kopię nocną przechowujemy **30 dni**, a jedną kopię miesięczną przez kolejne **12 miesięcy**.
Pliki usunięte z kursu pozostają w kopii **90 dni**, aby można było cofnąć przypadkowe
usunięcie, i następnie również są usuwane.

## Co się dzieje, gdy odchodzisz

Możesz zrezygnować w dowolnym momencie i zabrać swoje dane ze sobą. Przekazanie danych działa
jako **rotacja klucza**: to Ty generujesz nowy klucz szyfrujący, na własnym urządzeniu, i
przekazujesz nam tylko jego **część publiczną** — część prywatna nigdy nie opuszcza Twoich rąk.
Tym kluczem publicznym ponownie szyfrujemy aktualną kopię zapasową i przekazujemy Ci gotowe
archiwum. Nigdy nie ujawniamy współdzielonego klucza, który chroni kopie zapasowe innych szkół,
i nigdy nie mamy dostępu do Twojego klucza prywatnego. Dalej działa ten sam proces przywracania
serwera, który stawia Twoje dane tam, gdzie zdecydujesz się je uruchomić.

## Harmonogram

Wyślij prośbę o zmiany DNS opisaną wyżej, a Twoja strona może działać jeszcze tego samego dnia.
Poczta wychodząca — resetowanie haseł, powiadomienia — jest wysyłana przez port 587, domyślny
dla każdej szkoły i port, którego Hetzner nigdy nie zablokował.

Szkoła, która koniecznie chce korzystać z Microsoft Exchange Direct Send, może to zrobić przez
port 25. Hetzner domyślnie blokuje ten port i odblokowuje go tylko dla ustabilizowanego,
płacącego konta — w praktyce takiego, które ma 30 dni i co najmniej jedną rozliczoną fakturę.
Odblokowanie jest bezpłatne; daj nam znać wcześniej, jeśli wiesz, że będzie potrzebne.

## Plany

Przy podpisaniu umowy ustalamy pięć wartości:

- maksymalną liczbę uczniów na platformie,
- liczbę planowanych kursów,
- szacunkową liczbę filmów na kurs,
- typową długość filmu,
- oraz liczbę osób tworzących treści.

{libli:pricing_plans}

{libli:vat_note}
