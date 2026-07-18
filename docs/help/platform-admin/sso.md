# SSO (OIDC)

**Admin → Institution settings → SSO** lets you connect libli to an OpenID Connect
identity provider so staff and students can sign in with your institution's
existing accounts instead of a libli password.

![The SSO (OIDC) settings tab](static:core/img/help/sso.en.png)

## Configuring a provider

Fill in:

- **Display name** — a label for the provider, shown on the sign-in button.
- **Issuer / discovery URL** — the provider's OIDC issuer/discovery URL.
- **Client ID** and **Client secret** — issued by the provider when you
  register libli as an application. The secret is write-only: once saved,
  the form shows that a secret is on file rather than the value itself, and
  you only need to re-enter it if you're changing it.
- **Enable SSO** — turns the sign-in option on or off without discarding the
  rest of the configuration.

## Redirect URI

The page displays the exact **redirect URI** libli expects the provider to
send users back to after authentication. Register this URI verbatim in
your provider's application settings — a mismatch is the most common cause
of a failed handshake.

## Rolling out

Save the form to persist the configuration; leave **Enable SSO** unticked
first if you want to prepare a provider without exposing it to users yet. The
[first-run wizard](first-run-wizard) offers the same SSO step for a brand
new installation, and it can be skipped and configured later from here.
