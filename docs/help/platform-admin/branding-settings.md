# Branding & platform settings

**Admin → Institution settings** groups the institution-wide configuration into tabs.
This topic covers **Branding**, **Access** and **Uploads**; SSO,
Notifications and Integrations each have their own topic.

## Branding

Set the institution **name** and **logo** (2 MB max), the **primary** and
**accent** colours used throughout the interface (as 6-digit hex codes,
e.g. `#147E78`), the **default theme** (**Light**, **Dark** or **Auto** —
Auto is the default), and which **languages** are enabled for the
platform's own UI, with one of them chosen as the **default language**.
At least one language must stay enabled, and the default must be one of
the enabled ones.

## Access

Controls who can sign up and where from:

- **Signup policy** — either **Invite only** or **Open self-signup**;
  invitations (see [Invitations](invitations)) work regardless of this
  setting.
- **Allowed email domains** — one domain per line; leave it blank to allow
  any domain. This is advisory for invites (you get a warning, not a
  block) but is enforced for self-service sign-up.

## Uploads

Sets the safe ceiling for content media across the whole platform: which
**image** and **video** file types authors may upload, and the maximum size
in MiB for each. Course Admins cannot exceed these limits from the
content editors.

## Related topics

- [SSO (OIDC)](sso) — single sign-on configuration.
- [Integrations](integrations) — grade-sync webhook configuration.
- [Notifications](notifications) — email delivery and retention settings.
