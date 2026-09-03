# Branding & platform settings

**Admin → Institution settings** groups the institution-wide configuration into tabs.
This topic covers **Branding**, **Access** and **Uploads**; SSO,
Notifications and Integrations each have their own topic.

## Branding

![The branding settings tab](static:core/img/help/branding.en.png)

Set the institution **name** and **logo** (2 MB max), the **favicon** shown
in browser tabs and used as the home-screen icon on mobile (a square PNG,
192-512 px, 256 KB max — replaces the default libli icon), the **primary**
and **accent** colours used throughout the interface (as 6-digit hex codes,
e.g. `#147E78`), the **default theme** (**Light**, **Dark** or **Auto** —
Auto is the default), and which **languages** are enabled for the
platform's own UI, with one of them chosen as the **default language**.
At least one language must stay enabled, and the default must be one of
the enabled ones.

## Access

Controls who can sign up and where from:

- **Signup policy** — one of three, in order of openness:
  - **Invite only** — you create every account. No sign-up form.
  - **SSO only** — no sign-up form either, but anyone who signs in through
    your identity provider (see [SSO](sso)) gets an account automatically,
    restricted to the allowed email domains below. This is the setting for a
    school whose staff and pupils already have Microsoft or Google accounts:
    nobody can create a password that bypasses your own sign-in policies.
  - **Open self-signup** — anyone may register with a password, restricted to
    the allowed email domains below.

  Invitations (see [Invitations](invitations)) and sign-in for accounts that
  already exist work under **all three**, so switching to SSO only can never
  lock you out of your own platform.
- **Allowed email domains** — one domain per line; leave it blank to allow
  any domain. This is advisory for invites (you get a warning, not a
  block) but is enforced for self-service sign-up and for SSO.

## Uploads

Sets the safe ceiling for content media across the whole platform: which
**image** and **video** file types authors may upload, and the maximum size
in MiB for each. Course Admins cannot exceed these limits from the
content editors.

## Related topics

- [SSO (OIDC)](sso) — single sign-on configuration.
- [Integrations](integrations) — grade-sync webhook configuration.
- [Notifications](notifications) — email delivery and retention settings.
