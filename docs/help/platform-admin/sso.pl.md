# SSO (OIDC)

**Zarządzaj → Ustawienia → SSO** pozwala połączyć libli z dostawcą
tożsamości OpenID Connect, dzięki czemu pracownicy i uczniowie mogą się
logować przy użyciu już istniejących kont Twojej instytucji, zamiast hasła
do libli.

## Konfigurowanie dostawcy

Uzupełnij:

- **Nazwa** — etykieta dostawcy, widoczna na przycisku logowania.
- **Adres URL serwera** — adres wystawcy/discovery OIDC danego dostawcy.
- **Client ID** oraz **Client secret** — wydawane przez dostawcę przy
  rejestracji libli jako aplikacji. Sekret jest polem tylko do zapisu: po
  zapisaniu formularz pokazuje jedynie, że sekret jest zapisany, a nie jego
  wartość — trzeba go podać ponownie tylko wtedy, gdy chcesz go zmienić.
- **Włączone** — włącza lub wyłącza opcję logowania bez utraty pozostałej
  konfiguracji.

## Redirect URI

Strona wyświetla dokładny **redirect URI**, na który libli oczekuje
przekierowania użytkownika po uwierzytelnieniu. Zarejestruj ten adres
dokładnie w ustawieniach aplikacji u swojego dostawcy — jego niezgodność to
najczęstsza przyczyna nieudanego uwierzytelnienia.

## Wdrażanie

Zapisz formularz, aby utrwalić konfigurację; jeśli chcesz przygotować
dostawcę bez udostępniania go użytkownikom, najpierw wyłącz **Włączone**.
[Kreator pierwszego uruchomienia](first-run-wizard) oferuje ten sam krok
SSO dla świeżej instalacji — można go pominąć i skonfigurować później
właśnie tutaj.
