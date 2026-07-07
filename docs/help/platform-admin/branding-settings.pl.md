# Branding i ustawienia platformy

**Zarządzaj → Ustawienia** grupuje konfigurację obejmującą całą instytucję
w zakładki. Ten temat opisuje **Branding**, **Dostęp** i **Przesyłanie
plików**; SSO i Integracje mają swoje własne tematy.

## Branding

Ustaw **nazwę** instytucji i **logo** (maks. 2 MB), kolory **główny** i
**akcentu** używane w całym interfejsie (jako 6-cyfrowe kody hex, np.
`#147E78`), **domyślny motyw** (jasny/ciemny) oraz to, które **języki** są
włączone dla interfejsu platformy, wraz z wyborem jednego z nich jako
**domyślnego**. Co najmniej jeden język musi pozostać włączony, a domyślny
musi być jednym z włączonych.

## Dostęp

Kontroluje, kto i skąd może się zarejestrować:

- **Polityka rejestracji** — czy samodzielna rejestracja jest otwarta,
  ograniczona, czy wyłączona; zaproszenia (zobacz [Zaproszenia](invitations))
  działają niezależnie od tego ustawienia.
- **Dozwolone domeny e-mail** — jedna domena w wierszu; pozostaw puste, aby
  zezwolić na dowolną domenę. Przy zaproszeniach jest to ustawienie
  doradcze (dostajesz ostrzeżenie, nie blokadę), ale przy samodzielnej
  rejestracji jest egzekwowane.

## Przesyłanie plików

Ustala bezpieczny limit dla materiałów treści w całej platformie: jakie
typy plików **obrazów** i **wideo** mogą przesyłać autorzy oraz jaki jest
maksymalny rozmiar w MiB dla każdego z nich. Administratorzy Kursu nie mogą
przekroczyć tych limitów z poziomu edytorów treści.

## Powiązane tematy

- [SSO (OIDC)](sso) — konfiguracja logowania jednokrotnego.
- [Integracje (synchronizacja ocen)](integrations) — konfiguracja webhooka
  synchronizacji ocen.
- [Powiadomienia](notifications) — ustawienia dostarczania e-maili i
  retencji.
