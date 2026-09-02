# Branding i ustawienia platformy

**Administracja → Ustawienia instytucji** grupuje konfigurację obejmującą całą instytucję
w zakładki. Ten temat opisuje **Wygląd**, **Dostęp** i **Przesyłanie**; SSO,
Powiadomienia i Integracje mają swoje własne tematy.

## Wygląd

![Zakładka ustawień wyglądu](static:core/img/help/branding.pl.png)

Ustaw **nazwę** instytucji i **logo** (maks. 2 MB), **favicon** widoczny na
karcie przeglądarki i używany jako ikona na ekranie głównym urządzeń
mobilnych (kwadratowy plik PNG, 192-512 px, maks. 256 KB — zastępuje
domyślną ikonę libli), kolory **główny** i **akcentu** używane w całym
interfejsie (jako 6-cyfrowe kody hex, np. `#147E78`), **domyślny motyw**
(**Jasny**, **Ciemny** lub **Automatyczny** — domyślnie Automatyczny) oraz
to, które **języki** są włączone dla interfejsu platformy, wraz z wyborem
jednego z nich jako **domyślnego**. Co najmniej jeden język musi pozostać
włączony, a domyślny musi być jednym z włączonych.

## Dostęp

Kontroluje, kto i skąd może się zarejestrować:

- **Zasady rejestracji** — jedna z trzech opcji, od najbardziej zamkniętej:
  - **Tylko z zaproszeniem** — każde konto tworzysz samodzielnie. Nie ma
    formularza rejestracji.
  - **Tylko SSO** — również bez formularza rejestracji, ale każdy, kto
    zaloguje się przez Twojego dostawcę tożsamości (zobacz [SSO](sso)),
    automatycznie otrzymuje konto — z ograniczeniem do dozwolonych domen
    e-mail poniżej. To ustawienie dla szkoły, której nauczyciele i uczniowie
    mają już konta Microsoft lub Google: nikt nie może utworzyć hasła, które
    omijałoby Wasze własne zasady logowania.
  - **Otwarta samodzielna rejestracja** — każdy może założyć konto z hasłem,
    z ograniczeniem do dozwolonych domen e-mail poniżej.

  Zaproszenia (zobacz [Zaproszenia](invitations)) oraz logowanie na istniejące
  konta działają przy **wszystkich trzech**, więc przełączenie na Tylko SSO
  nigdy nie zablokuje Ci dostępu do własnej platformy.
- **Dozwolone domeny e-mail** — jedna domena w wierszu; pozostaw puste, aby
  zezwolić na dowolną domenę. Przy zaproszeniach jest to ustawienie
  doradcze (dostajesz ostrzeżenie, nie blokadę), ale przy samodzielnej
  rejestracji i przy SSO jest egzekwowane.

## Przesyłanie

Ustala bezpieczny limit dla materiałów treści w całej platformie: jakie
typy plików **obrazów** i **wideo** mogą przesyłać autorzy oraz jaki jest
maksymalny rozmiar w MiB dla każdego z nich. Administratorzy kursu nie mogą
przekroczyć tych limitów z poziomu edytorów treści.

## Powiązane tematy

- [SSO (OIDC)](sso) — konfiguracja logowania jednokrotnego.
- [Integracje (synchronizacja ocen)](integrations) — konfiguracja webhooka
  synchronizacji ocen.
- [Powiadomienia](notifications) — ustawienia dostarczania e-maili i
  retencji.
