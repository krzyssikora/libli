# Informacja o ochronie danych osobowych

Obowiązuje od 29 sierpnia 2026 r.

Niniejsza informacja dotyczy serwisu libli o nazwie: {libli:site_name}. Opisuje, co ten serwis
przechowuje na Twój temat, kto ma do tego wgląd, jak długo dane są przechowywane i jak można
wystąpić o ich zmianę lub usunięcie.

## Kto odpowiada za Twoje dane

Administratorem Twoich danych osobowych jest: {libli:controller_name}.

{libli:controller_address}

Kontakt w sprawie tej informacji oraz wniosków opisanych niżej w części o prawach:
{libli:contact_email}.

{libli:demo_notice}

## Jakie dane przechowujemy i po co

**Konto i dane identyfikacyjne.** Nazwa użytkownika, którą ma każde konto. Adres e-mail, który
jest opcjonalny — libli potrzebuje go wyłącznie do resetu hasła, zaproszeń i powiadomień pocztą.
Nazwa wyświetlana oraz imię i nazwisko, jeśli szkoła je uzupełni. Rola przypisana do konta: Uczeń,
Nauczyciel, Administrator kursów lub Administrator platformy.

**Numer w rejestrze lub numer ucznia.** Administrator platformy może zapisać przy Twoim koncie
zewnętrzny numer z rejestru albo numer ucznia. Samo libli nic z nim nie robi, ale jest to jedno z
pól wysyłanych przez webhook z wynikami, opisany niżej w części o usługach zewnętrznych — na
wdrożeniach, na których administrator ten webhook włączył.

**Jeśli logowanie odbywa się przez dostawcę tożsamości szkoły.** Przy takim koncie libli
przechowuje u siebie dodatkowo: informację, który to dostawca, identyfikator, jakim posługuje się
u niego Twoje konto, datę pierwszego połączenia konta i datę ostatniego logowania oraz zwrócone
przez dostawcę dane o Tobie — zwykle imię, nazwisko i adres e-mail — zapisane w takiej postaci, w
jakiej przyszły. **libli nie przechowuje tokenów dostępu** wystawianych przez dostawcę, więc nie
ma u siebie niczego, czym można by sięgnąć do Twojego konta po tamtej stronie.

**Zapis Twojej nauki.** Które lekcje zostały otwarte na Twoim koncie, które ich fragmenty zostały
wyświetlone i które lekcje oznaczono jako ukończone; na jakie kursy jest zapisane Twoje konto;
Twoje podejścia do testów wraz z czasem przesłania oraz zapisanym wynikiem i wynikiem
maksymalnym; a także same odpowiedzi, razem z pisemną informacją zwrotną nauczyciela.
Ćwiczenia wykonywane w obrębie lekcji — przestawione elementy, luki uzupełnione poza testem — też
są zapisywane przy Twoim koncie i nie są pokazywane w analityce nauczyciela.

**Każda przesłana odpowiedź jest przechowywana wraz z czasem jej przesłania — nie tylko ta
ostatnia.** Jeśli odpowiesz na to samo pytanie trzy razy, zostaną wszystkie trzy odpowiedzi, każda
ze swoim znacznikiem czasu. Poprawienie odpowiedzi nie kasuje poprzednich.

**Grupy, klasy i kohorty.** Do jakich grup należysz, przy jakim kursie stoi każda z nich i którzy
nauczyciele ją prowadzą. Także kohorta — rocznik lub nabór, do którego szkoła przypisuje konta —
do której przypisano Twoje konto, wraz z informacją, kto i kiedy tego przypisania dokonał.

**Twoje własne notatki, etykiety i pliki.** Prywatne notatki dopięte do lekcji oraz kolorowe
etykiety nakładane na lekcje są zapisywane przy Twoim koncie. Pliki dodane do biblioteki mediów
kursu są zapisywane wraz z kontem, które je dodało.

**Ustawienia.** Język interfejsu, jasny lub ciemny wygląd oraz to, czy chcesz otrzymywać
powiadomienia pocztą.

**Zgłoszenia problemów.** Jeśli wyślesz zgłoszenie problemu, libli zapisuje jego treść, adres i
tytuł strony, z której zgłoszenie zostało wysłane, załączony przez Ciebie zrzut ekranu, Twoją
nazwę wyświetlaną, nazwę użytkownika, adres e-mail i role posiadane w tamtym momencie, a także
krótki opis techniczny przeglądarki: jej sygnaturę user-agent, rozmiar okna i ekranu, gęstość
pikseli, ustawienie wyglądu, język interfejsu, nagłówek języka i strefę czasową.

Wysłanie zgłoszenia to nie tylko jego zapisanie. **Jego treść jest wysyłana pocztą** — to, co
zostało napisane, strona, z której przyszło, cały opis techniczny, Twoja nazwa wyświetlana, nazwa
użytkownika i adres e-mail oraz zrzut ekranu w załączniku — do każdego Administratora platformy,
który ma adres e-mail, oraz na wszystkie dodatkowe adresy skonfigurowane przez operatora do
odbierania zgłoszeń. Te dodatkowe adresy to te, które wpisał operator; nie muszą należeć do
nikogo, kto ma jakąkolwiek rolę w libli.

Wszystko to istnieje po to, żeby kursy działały, żeby nauczyciel mógł ocenić Twoją pracę i dać Ci
informację zwrotną oraz żeby szkoła mogła zarządzać kontami. Podstawę prawną przetwarzania
określa organizacja wskazana wyżej jako administrator, a nie libli; jeśli potrzebujesz jej na
piśmie, zwróć się do adresata wskazanego wyżej, w części o tym, kto odpowiada za dane.

## Czego libli nie zbiera

- **Żadnych adresów IP w samej aplikacji.** Żadna część libli nie odczytuje ani nie zapisuje
  adresu, z którego łączy się Twoja przeglądarka. (Serwer WWW stojący przed aplikacją prowadzi
  własne logi dostępu — patrz punkt o usługach zewnętrznych poniżej.)
- **Żadnej analityki i żadnego śledzenia.** Nie ma tu pakietu analitycznego, piksela śledzącego
  ani skryptu obcej firmy na stronach samego libli. Arkusze stylów, skrypty i kroje pisma są
  serwowane z tego serwisu.
- **Żadnych reklam** i żadnych danych przekazywanych sieciom reklamowym.
- **Żadnego profilowania ani zautomatyzowanego podejmowania decyzji.** Pytania testowe o
  ustalonej odpowiedzi są sprawdzane automatycznie względem klucza, a nauczyciel może zmienić
  każdą ocenę; odpowiedzi otwarte czyta człowiek. Nic z tego nie prowadzi do decyzji podjętej
  wyłącznie w sposób zautomatyzowany.
- **Nic nie jest sprzedawane i nic nie jest udostępniane w celach marketingowych.**
- **Żadnych plików cookie poza funkcjonalnymi wymienionymi niżej.**

## Pliki cookie i pamięć przeglądarki

libli ustawia cztery pliki cookie, wszystkie własne i wszystkie funkcjonalne:

| Cookie | Do czego służy | Czas życia |
| --- | --- | --- |
| `sessionid` | Utrzymuje zalogowanie, a przed zalogowaniem zapamiętuje wybrany język | Dwa tygodnie. Jest to cookie trwałe, nie sesyjne: przetrwa zamknięcie przeglądarki |
| `csrftoken` | Zabezpieczenie przed sfałszowaniem żądania przy wysyłaniu formularzy | Około roku. Nie zawiera niczego, co Cię identyfikuje |
| `messages` | Przenosi jednorazowy komunikat o powodzeniu lub błędzie na kolejną stronę | Krótkotrwałe; znika, gdy komunikat zostanie wyświetlony |
| `libli_theme` | Twój wybór jasnego lub ciemnego wyglądu | Rok |

libli trzyma też kilka ustawień interfejsu w pamięci lokalnej przeglądarki — które panele zostały
rozwinięte w konspekcie kursu, czy panel nawigacji lub listy uczniów jest zwinięty, jaki tryb
widoku był ostatnio używany w edytorze kursu. Zapisują je własne skrypty libli pod kluczami
zaczynającymi się od `libli_`, `libli:` lub `libli-`. Nigdy nie opuszczają Twojej przeglądarki,
nie zawierają niczego, co Cię identyfikuje — najwyżej identyfikator kursu lub elementu strony — a
wyczyszczenie danych witryny je usuwa.
Opisujemy je przez przedrostek, a nie przez wyliczenie, żeby ten akapit pozostał prawdziwy także
wtedy, gdy nowa funkcja doda kolejny klucz.

## Usługi zewnętrzne

**Materiały osadzone.** Nauczyciel może umieścić w lekcji film lub interaktywny arkusz innego
dostawcy. To, którzy dostawcy są dopuszczeni, ustala operator tego serwisu. Obecnie:
{libli:embed_domains}. Twoja przeglądarka łączy się z którymkolwiek z nich wyłącznie na stronie, w
której nauczyciel faktycznie osadził taki materiał — na każdej innej stronie, łącznie z tą, nie
łączy się z nimi wcale. Tam, gdzie się łączy, dostawca otrzymuje Twój adres IP i żądanie
osadzonego materiału oraz **może zapisać w Twojej przeglądarce własne pliki cookie i własne dane**
na własnych warunkach, na które libli nie ma wpływu.

Jeśli dopuszczony dostawca ma siedzibę poza Europejskim Obszarem Gospodarczym, połączenie zachodzi
bezpośrednio między Twoją przeglądarką a tym dostawcą, na jego własnych warunkach. libli nie jest
stroną tego połączenia i samo niczego nie przekazuje.

**Logowanie jednokrotne (SSO).** Jeśli szkoła loguje Cię przez własnego dostawcę tożsamości, ten
dostawca przekazuje libli, kim jesteś — identyfikator oraz, jeśli szkoła tak to skonfiguruje,
Twoje imię, nazwisko i adres e-mail. libli nie odsyła mu żadnego zapisu Twojej nauki.

**Poczta.** Reset hasła, zaproszenia, powiadomienia i zgłoszenia problemów są wysyłane przez
serwer pocztowy skonfigurowany przez operatora tego serwisu. Ten serwer przetwarza Twój adres
e-mail i treść tych wiadomości, w tym wszystko, co niesie ze sobą zgłoszenie problemu.

**Webhook z wynikami.** Administrator może włączyć webhook przekazujący zatwierdzone wyniki testów
do innego systemu — na przykład do dziennika szkolnego. Jest wyłączony, dopóki administrator go
nie włączy, i dotyczy wyłącznie kursów z nadanym kodem zewnętrznym. Gdy jest włączony, każdy
zatwierdzony wynik wysyła pod skonfigurowany adres Twój numer w rejestrze lub numer ucznia, adres
e-mail, nazwę widoczną na Twoim koncie, kurs, to, o który test chodzi, grupę i wynik.

**Logi dostępu serwera WWW.** Serwer WWW obsługujący ten serwis prowadzi logi dostępu i **te logi
zapisują adresy IP**, mimo że sama aplikacja nigdy ich nie przechowuje. Czas ich przechowywania
ustala ten, kto prowadzi serwer, a nie libli.

**Obrazy dodawane przez adres URL.** Gdy nauczyciel dodaje obraz, wklejając odnośnik, to
**serwer** pobiera ten obraz z hosta z listy dozwolonych i zapisuje tutaj jego kopię;
przeglądarki czytelników nigdy nie łączą się z pierwotnym hostem. Takie pobranie nie niesie ze
sobą żadnych informacji o Tobie ani o innym użytkowniku. Tak samo działa odpytanie o rozmiar
apletu, które libli wykonuje w geogebra.org, gdy nauczyciel wkleja odnośnik do GeoGebry.

## Kto widzi Twoje dane

- **Ty** widzisz swój własny zapis.
- **Nauczyciel** widzi pracę uczniów z grup, które prowadzi, na kursach, przy których te grupy
  stoją — i nic o uczniach z innych grup.
- **Administrator kursów** widzi kursy, których jest właścicielem, w tym zapis każdego zapisanego
  na nie ucznia.
- **Administrator platformy** ma dostęp do wszystkiego w serwisie: do każdego konta, każdego kursu
  i każdego zapisu nauki. Po to jest ta rola.
- **Uczniowie nie widzą nic o sobie nawzajem.** Nie pokazujemy Ci odpowiedzi, wyników ani postępów
  innego ucznia, a Twoich nie pokazujemy jemu.
- **Twoje notatki i etykiety są tylko Twoje.** Nie wyświetla ich żaden ekran nauczyciela ani
  administratora.
- **Dostęp do treści kursów to inna sprawa niż dane osobowe.** Każde konto, które nie jest kontem
  ucznia — Nauczyciel, Administrator kursów, Administrator platformy — może otworzyć każdy kurs w
  tym serwisie, niezależnie od tego, czy go prowadzi. Daje to dostęp do materiału, a nie do
  czyjegokolwiek zapisu nauki, o którym rozstrzygają punkty powyżej.

Każdy, kto ma bezpośredni dostęp do serwera lub jego bazy danych, może oczywiście odczytać
wszystko, co jest tam zapisane. Ten dostęp należy do organizacji wskazanej wyżej i do podmiotów,
którym powierza ona prowadzenie serwisu.

## Jak długo przechowujemy dane

Przeczytane powiadomienia są usuwane {libli:retention_phrase}. Istotne są dwa zastrzeżenia.
Usuwanie nie dzieje się samo z siebie: rekordy znikają wtedy, gdy zostanie uruchomione zadanie
czyszczące, które musi zaplanować wdrożenie operatora, albo gdy uruchomi je Administrator platformy
z panelu ustawień — we wdrożeniu, w którym nikt takiego harmonogramu nie ustawił, nie jest usuwane
nic. Powiadomienia **nieprzeczytane** nigdy nie są usuwane ze względu na wiek.

Zapis Twojej nauki — zapisy na kursy, postępy, podejścia, odpowiedzi i próby — **nie ma żadnego
automatycznego terminu wygaśnięcia.** Jest przechowywany tak długo, jak istnieje konto, a jego
usunięcie jest ręczną czynnością administratora.

Zgłoszenia problemów i załączone do nich zrzuty ekranu są przechowywane, dopóki nie skasuje ich
Administrator platformy. Nic nie usuwa ich ze względu na wiek. Kopie rozesłane już pocztą są poza
kontrolą libli.

**Kopie zapasowe.** Serwer jest co noc kopiowany na zaszyfrowany nośnik w Unii Europejskiej.
Kopię nocną przechowujemy **30 dni**, a jedną kopię miesięczną przez kolejne **12 miesięcy** —
żadna kopia nie jest więc starsza niż około **13 miesięcy**, po czym zostaje trwale usunięta.
Pliki usunięte z kursu pozostają w kopii **90 dni**, aby można było cofnąć przypadkowe
usunięcie, i następnie również są usuwane. Zrzut ekranu dołączony do zgłoszenia problemu
znika z kopii tej samej nocy, w której usuniemy go z serwisu — bez opóźnienia.

Kopie są szyfrowane kluczem, którego nie ma na serwerze, więc osoba, która przejęłaby serwer,
nie mogłaby ich odczytać.

## Twoje prawa

Możesz żądać dostępu do dotyczących Cię danych osobowych, ich sprostowania, ich usunięcia,
ograniczenia ich przetwarzania oraz ich kopii w formacie nadającym się do przeniesienia; możesz
też wnieść sprzeciw wobec przetwarzania. Tam, gdzie przetwarzanie opiera się na zgodzie, możesz ją
wycofać, co nie wpływa na to, co zrobiono przed jej wycofaniem.

Możesz również wnieść skargę do organu nadzorczego. Właściwy organ nadzorczy to:
{libli:supervisory_authority}.

Trzy uwagi praktyczne, podane wprost, bo zmieniają to, czego należy się spodziewać:

- **Nie ma samoobsługowego eksportu ani samoobsługowego usunięcia konta.** libli nie ma przycisku,
  który pobierze Twoje dane albo skasuje Twoje konto.
- **Wnioski są obsługiwane ręcznie.** Swój skieruj do adresata wskazanego wyżej, w części o tym,
  kto odpowiada za dane, a zajmie się nim człowiek.
- **Dezaktywacja konta to nie jest usunięcie danych.** Dezaktywowane konto nie może się już
  zalogować, ale samo konto i wszystko, co jest z nim związane, pozostaje w bazie danych, dopóki
  ktoś tego nie skasuje.

## Dzieci

libli powstało dla szkół i wiele osób z niego korzystających to dzieci. Konta zakłada i prowadzi
szkoła i to szkoła decyduje, jakie dane identyfikacyjne w nich umieści. Tam, gdzie potrzebna jest
zgoda dotycząca danych dziecka, jest to sprawa między szkołą a rodzicem lub opiekunem — samo libli
nie prosi dzieci o żadną zgodę i nie zbiera niczego poza tym, co opisuje ta informacja.

## Bezpieczeństwo

Konfiguracja produkcyjna, w której działa ten serwis, przekierowuje zwykłe połączenia HTTP na
HTTPS i oznacza pliki cookie sesji oraz zabezpieczenia formularzy jako bezpieczne, więc są
przesyłane wyłącznie połączeniem szyfrowanym. Utrzymanie tej konfiguracji, serwera i kopii
zapasowych w bezpiecznym stanie należy do organizacji wskazanej wyżej.

Niezależnie od decyzji wdrożeniowych: hasła nigdy nie są przechowywane, a jedynie ich solony skrót
liczony mechanizmem haszowania haseł Django; to, co dane konto może zobaczyć, jest rozstrzygane na
podstawie jego roli przy każdym pojedynczym żądaniu, a nie przez ukrywanie odnośników; a zrzuty
ekranu załączone do zgłoszeń problemów są zapisywane poza katalogiem mediów serwowanym przez WWW i
są w samym libli udostępniane wyłącznie Administratorowi platformy i nikt nie pobierze ich,
zgadując adres. Wychodzą jednak również jako załącznik wiadomości ze zgłoszeniem, o czym mowa
wyżej.

## Zmiany tej informacji

Data obowiązywania na górze tej strony zmienia się za każdym razem, gdy zmienia się ta informacja.
Organizacja prowadząca ten serwis może opublikować własną wersję tej strony zamiast tej, którą
dostarcza libli; tekst, który czytasz, jest tym obowiązującym w tym serwisie.
