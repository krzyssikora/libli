# Phase 5d — SSO Configuration UI: Design Spec

*Spec date: 2026-06-30. A sub-phase of Phase 5 of the [libli roadmap](../../roadmap.md)
(roadmap §Phase 5 "SSO configuration UI"). Builds directly on
[Phase 0c‑2 (SSO + JIT provisioning)](2026-06-14-phase-0c2-sso-jit-provisioning-design.md),
which already implemented the OIDC backend (django-allauth `socialaccount` +
`openid_connect`, the `SocialAccountAdapter`, JIT provisioning gating, the conditional
login-page "Continue with …" button, and the not-provisioned page), and on
[Phase 5c (Branding & Platform Settings)](2026-06-29-phase-5c-branding-and-platform-settings-design.md),
whose `/manage/settings/` tabbed surface this phase extends with a fourth tab.*

## Goal

Give the Platform Admin a **bespoke, in-product UI to configure the institution's single
OpenID Connect (OIDC) SSO provider**, replacing today's only configuration path: editing a
`SocialApp` row in the Django admin. After 5d a PA can set the provider's display name,
issuer/discovery URL, client ID, and client secret; **enable or disable** SSO with a single
toggle (without losing the saved secret); and read the **redirect/callback URI** to register
with their IdP — all from `/manage/settings/?tab=sso`, never touching Django admin.

The SSO *runtime* is unchanged. The login button and JIT provisioning already work off whatever
`SocialApp` is configured; 5d only changes **how that row gets created and edited**.

## Scope boundary (decided during brainstorming, 2026-06-30)

**In scope (5d):**
- A **single-provider**, edit-in-place SSO config form backed by allauth's existing `SocialApp`
  model (`provider="openid_connect"`). **No new model, no migration.**
- A new **"SSO" tab** in the existing `/manage/settings/` surface (4th tab beside
  Branding / Access / Uploads), reusing Phase 5c's shared template + per-tab POST action pattern.
- An explicit **"Enabled" toggle** distinct from the credentials: off = login button hidden but
  client id / secret / issuer retained; on = button shown. Implemented by attaching/detaching the
  current `Site` from `SocialApp.sites`.
- **Write-only client secret:** the stored secret is never rendered back to the browser; a blank
  secret field preserves the existing secret, a typed value replaces it.
- A read-only, copyable **redirect URI** display (`…/accounts/oidc/sso/login/callback/`) for the
  PA to register with their IdP.
- **Format-only validation** (required fields + well-formed **https** issuer URL); no outbound
  network call.
- SSO config logic lives in the **`accounts`** app (owner of all SSO code since 0c‑2); the
  `institution` settings surface renders the tab and delegates.
- Focused tests for the service, form validation, enable/disable site-attachment, view
  permission/PRG, redirect-URI rendering, and one e2e (configure → enable → button appears).

**Out of scope — deferred:**
- **Multiple SSO providers** (a list/CRUD): single-tenant schools need one IdP; the model and the
  fixed `provider_id` are chosen so multi-provider could be added later, but it is not built now.
- **SAML.**
- A **live "Test connection" / discovery probe** (server-side GET of
  `<issuer>/.well-known/openid-configuration`): allauth already fetches discovery at first login,
  so a wrong URL surfaces then; the live test adds an outbound-HTTP view + timeout/SSRF surface and
  is deferred.
- **Role-bearing provisioning** (SSO users still land as Student; a PA promotes afterward — the
  0c‑2 rule is unchanged).
- **Provider-specific allauth apps** (`google`, `microsoft`): the generic `openid_connect`
  provider covers them.

## Execution environment

Windows (win32), PowerShell primary; every `bash` block runs through the Bash tool / Git Bash
(POSIX sh). System `python`/`ruff`/`pytest` are **not** on PATH — always invoke through
**`uv run …`** (`uv run python manage.py …`, `uv run pytest`, `uv run ruff check .`,
`uv run ruff format .`). Run `uv run ruff format .` before every commit; `ruff check` enforces
E501 (≤88 cols). i18n: after `makemessages`, clear spurious `#, fuzzy` flags and verify new PL
msgids (the makemessages fuzzy/mis-guess gotcha); compile `.mo`. Tests reuse
`tests.factories.TEST_PASSWORD` and the existing factories; **no hard-coded password literals**
(GitGuardian CI flags them).

---

## Components

All new SSO code lives in the existing **`accounts`** app; the **settings surface stays in
`institution`** (Phase 5c) and delegates to `accounts`. The `SocialApp`/`Site` models are
allauth/Django built-ins — **no project model is added, so there is no migration**.

| Unit | File | Responsibility |
|---|---|---|
| SSO config service | `accounts/sso_config.py` *(new)* | Load / save / enable / disable the single OIDC `SocialApp`. The sole place that touches `SocialApp` + `Site`. Pure of HTTP/view coupling. |
| SSO form | `accounts/forms.py` *(modified — file exists)* | `SsoForm(forms.Form)`: fields, validation, write-only secret, enable-completeness rule. |
| Settings views | `institution/views_manage.py` *(modified)* | Add `"sso"` to `TABS`; seed the `sso` form into `_settings_context`; new `settings_sso` POST action (PRG) delegating to the service. |
| URL | `institution/urls.py` *(modified)* | `manage/settings/sso/` → `name="settings_sso"`. |
| Templates | `templates/institution/manage/settings.html`, `_tabs.html` *(modified)*; `templates/institution/manage/_sso_tab.html` *(new)* | Fourth tab + the SSO form panel (enable toggle, 4 fields, "secret saved" hint, redirect-URI block). |
| Styles | `static/institution/settings.css` *(modified)* | Any SSO-specific styling (redirect-URI block, toggle) reusing the existing `settings__*` classes. |
| Tests | `tests/test_sso_config.py` *(new)*; e2e under existing e2e dir | Service, form, view, redirect-URI, enable/disable; one e2e. |

---

## 1. The config service (`accounts/sso_config.py`)

A small module isolating every read/write of the allauth `SocialApp` + `Site`, so the form and
view never query allauth models directly. Constants:

```
OIDC_PROVIDER   = "openid_connect"   # allauth provider key
OIDC_PROVIDER_ID = "sso"             # fixed slug → stable redirect URI
```

`provider_id` is a **constant**, not derived from the institution name, precisely so the redirect
URI the PA registers with their IdP never changes. The single-provider invariant is "the one row
with `provider="openid_connect"`".

**Functions:**

- `load_sso_app() -> SocialApp | None` — `SocialApp.objects.filter(provider=OIDC_PROVIDER).first()`.
  Returns `None` when SSO has never been configured. (Single-provider invariant: filter on
  `provider`, take first; a stray duplicate is ignored, never created by this UI.)
- `is_enabled(app, site) -> bool` — `app is not None and app.sites.filter(pk=site.pk).exists()`.
- `redirect_uri(request) -> str` — `request.build_absolute_uri(reverse("openid_connect_callback",
  kwargs={"provider_id": OIDC_PROVIDER_ID}))`. (Resolves to `…/accounts/oidc/sso/login/callback/`;
  built from the request so scheme+host are correct behind the deployment's proxy.) **Note:** the
  allauth URL name `openid_connect_callback` takes a `provider_id` kwarg and exists regardless of
  whether a `SocialApp` is configured (the route is registered at import time), so the URI can be
  shown before first save.
- `save_sso_config(*, name, server_url, client_id, client_secret, enabled, site) -> SocialApp`
  — inside `transaction.atomic()`:
  1. `app, _ = SocialApp.objects.get_or_create(provider=OIDC_PROVIDER,
     provider_id=OIDC_PROVIDER_ID)` — no `defaults` needed; every persisted field is set
     explicitly in steps 2–3 before the single `save()` in step 4 (a freshly created row is saved
     once, fully populated).
  2. Set `app.name = name`, `app.client_id = client_id`; merge issuer into JSON settings:
     `app.settings = {**app.settings, "server_url": server_url}`.
  3. **Secret:** set `app.secret = client_secret` **only if** `client_secret` is non-empty;
     otherwise leave the stored secret untouched. (The form passes `""` when the PA left it blank.)
  4. `app.save()`.
  5. **Enable toggle:** `app.sites.add(site)` if `enabled` else `app.sites.remove(site)`
     (idempotent; the M2M is the single source of "live", credentials are preserved on disable).
  6. Return `app`.

  The form's `clean` guarantees `save_sso_config` is only called with a complete-enough payload
  (see §2), so the service does not itself re-enforce the enable-completeness rule — but it still
  only **creates** a row when called (i.e. the view calls it only on a valid POST, never on GET),
  so a never-configured install has no `SocialApp` row.

The current `Site` is resolved by the **caller** (view) via
`django.contrib.sites.shortcuts.get_current_site(request)` and passed in, keeping the service free
of request coupling. (`SITE_ID = 1` is set; 0c‑2 ties the `SocialApp` to the Site.)

## 2. The form (`accounts/forms.py` → `SsoForm`)

A plain `forms.Form` (not a `ModelForm`: `settings` is JSON, `sites` is M2M, and the secret is
write-only — none map cleanly to `ModelForm` fields).

**Fields** (all labels/help via `gettext_lazy` — module-level form text must be **lazy**, per the
eager-gettext-froze-labels gotcha):

| Field | Definition |
|---|---|
| `enabled` | `BooleanField(required=False)` — the live toggle. |
| `name` | `CharField(required=False, max_length=40)` — button label ("Continue with {name}"); `40` matches `SocialApp.name`'s column width. |
| `server_url` | `URLField(required=False)` — issuer / discovery base. |
| `client_id` | `CharField(required=False)` — OIDC client id. |
| `client_secret` | `CharField(required=False, widget=forms.PasswordInput(render_value=False))` — write-only. |

All fields are `required=False` at the field level; **completeness is enforced conditionally in
`clean`** (a disabled, partially-filled config is allowed; enabling demands a full config). This
keeps "save a draft while disabled" and "must be complete to go live" as one coherent rule.

**Initial seeding** (constructed by the view from the service, GET and error re-render):
- `enabled` ← `is_enabled(app, site)`; `name` ← `app.name`; `server_url` ←
  `app.settings.get("server_url", "")`; `client_id` ← `app.client_id`; all blank when `app is None`.
- `client_secret` initial is **always empty** (never seeded). The template separately shows
  whether a secret is on record (see §3) via a `secret_saved` context flag — **not** via the field
  value, so the secret is never serialized to HTML.

**Validation (`clean`):**
- `server_url`, when non-empty, must be a **well-formed https URL**. `URLField` already validates
  URL shape; add a scheme check rejecting non-`https` (OIDC mandates TLS) with a clear error on the
  `server_url` field. A trailing slash is accepted; the value is stored verbatim (allauth appends
  the discovery path).
- **Enable-completeness:** if `cleaned_data["enabled"]` is true, then `name`, `server_url`, and
  `client_id` must all be non-empty, **and** a secret must be available — i.e. either a non-empty
  `client_secret` was typed **or** a secret is already stored (`bool(app and app.secret)`). The
  form is given the loaded `app` (or `None`) at construction so it can check the stored-secret case.
  Missing pieces raise field errors (`name`/`server_url`/`client_id`) or, for the secret,
  a `client_secret` field error: *"Enter the client secret to enable SSO."* This blocks a
  half-configured provider from going live.
- When `enabled` is false, no completeness is required (the PA may save a partial draft or blank
  everything); whatever is filled is persisted, the `Site` is detached.

**No secret in the form's cleaned output beyond what was typed:** `clean` does not read or copy the
stored secret into `cleaned_data`; the "keep existing" behavior lives entirely in the service
(blank ⇒ untouched).

## 3. Views, URL & template

**`institution/views_manage.py`** (follows the 5c pattern exactly):
- `TABS = ("branding", "access", "uploads", "sso")`.
- `_settings_context(...)` gains an `sso` key. Because `SsoForm` needs the loaded `app` and the
  current `Site` (for seeding + the enable-completeness check + the `secret_saved`/`redirect_uri`
  template flags), the context builder (or the view) resolves `app = load_sso_app()` and
  `site = get_current_site(request)` and constructs `SsoForm(initial=..., app=app)` plus context
  entries `sso_secret_saved = bool(app and app.secret)` and `sso_redirect_uri = redirect_uri(request)`.
  (The existing three forms are seeded from `Institution`; SSO is seeded from the service — same
  shape, different source.)
- New action view `settings_sso(request)`: `@login_required` +
  `@permission_required("institution.change_institution", raise_exception=True)` (same guard as the
  other tabs — the PA has it). GET → redirect to `?tab=sso` (POST-target contract). POST → bind
  `SsoForm(request.POST, app=load_sso_app())`; if valid, call `save_sso_config(...)` with the
  current site, `messages.success(request, _("SSO settings saved."))`, redirect to `?tab=sso` (PRG);
  if invalid, re-render `settings.html` with the bound form (active tab `sso`).

**`institution/urls.py`:** add
`path("manage/settings/sso/", views_manage.settings_sso, name="settings_sso")`.

**Templates:**
- `_tabs.html`: add a fourth `<a class="settings__tab …">{% trans "SSO" %}</a>` →
  `?tab=sso`, mirroring the existing three.
- `settings.html`: add a `<div data-tab="sso" {% if active_tab != "sso" %}hidden{% endif %}>
  {% include "institution/manage/_sso_tab.html" %}</div>` block.
- **`_sso_tab.html`** *(new)* — a `<form method="post"
  action="{% url 'institution:settings_sso' %}">` styled with the existing `settings__*` classes:
  - `{% csrf_token %}` + `{{ sso.non_field_errors }}`.
  - **Enabled toggle** (`{{ sso.enabled }}` + label) with help text explaining off = button hidden,
    credentials kept.
  - **Display name**, **Issuer / discovery URL**, **Client ID** fields (label + widget +
    `help_text` + `.errors`, same markup as `_access_tab.html`).
  - **Client secret** field; directly above/below it, when `sso_secret_saved`, a
    `settings__help` line: *"A client secret is saved. Leave blank to keep it; enter a value to
    replace it."* When not saved: *"Enter the client secret from your IdP."*
  - **Redirect URI block** — a read-only, copyable display of `{{ sso_redirect_uri }}` with a
    `settings__help` note: *"Register this redirect URI with your identity provider."* (Plain
    selectable text / read-only input; no JS clipboard dependency required, though a small
    copy affordance is acceptable if it matches the design system.)
  - `settings__actions` → `<button class="btn">{% trans "Save SSO settings" %}</button>`.

**Styling.** Reuse `settings__form/section/field/label/help/actions`. Add minimal CSS only for the
redirect-URI block and the toggle if the existing classes don't cover them. **Verify light + dark +
mobile via throwaway Playwright screenshots** (delete-after-review) before shipping, per house rule
(every view ships styled).

## Data flow

**Configure & enable:** PA opens `/manage/settings/?tab=sso` → GET renders `SsoForm` seeded from
the `SocialApp` (or blank), shows redirect URI + "secret saved?" hint → PA fills fields, checks
**Enabled**, submits → `settings_sso` POST → `clean` passes completeness → `save_sso_config`
get-or-creates the row, stores name/issuer/client_id/secret, **adds** the Site → redirect
`?tab=sso` with success message → login page's existing `{% get_providers %}` now returns the
provider → "Continue with {name}" button appears.

**Disable (keep secret):** PA unchecks **Enabled**, submits → service **removes** the Site from
`app.sites`; `name/client_id/secret/settings` untouched → login button disappears; re-enabling
later needs no re-entry of the secret.

**Rotate secret:** PA types a new value in **Client secret**, submits → service overwrites
`app.secret`. Leaving it blank on any later save preserves it.

## Error handling

- **Invalid submit** (enabling while incomplete, non-https issuer) → form re-renders on the `sso`
  tab with field-level errors; nothing saved (no partial write — the single `save_sso_config` call
  is gated on `form.is_valid()`).
- **Non-PA access** → `permission_required(raise_exception=True)` → 403 (same as the other tabs).
- **GET on the action URL** → redirect to `?tab=sso` (method contract).
- **Secret never leaks** — the stored secret is not seeded into the field nor placed in
  `cleaned_data`/context; only `secret_saved` (a boolean) reaches the template.
- **No row yet** — `load_sso_app()` returns `None`; the form is all-blank, the redirect URI still
  renders (route exists at import time), and the first valid enabled save creates the row.

## Testing (no live IdP)

`tests/test_sso_config.py` (+ an e2e in the existing e2e suite). No network; no DB-layer mocking
(project rule). Use a fresh `Site`/`SocialApp` per test.

- **Service:** `save_sso_config` creates the row with `provider="openid_connect"`,
  `provider_id="sso"`; round-trips name/issuer (in `settings["server_url"]`)/client_id; **secret
  kept** when `client_secret=""`, **replaced** when non-empty; `enabled=True` adds the Site,
  `enabled=False` removes it; `redirect_uri` ends with `/accounts/oidc/sso/login/callback/`;
  `is_enabled` reflects Site membership.
- **Form:** non-https `server_url` → error; `enabled=True` with a missing field → field error;
  `enabled=True`, no stored secret, blank `client_secret` → `client_secret` error; `enabled=True`
  with a stored secret + blank `client_secret` → **valid** (keep-existing); `enabled=False`
  partial/blank → valid; the field never renders the stored secret (assert the secret string is
  absent from the rendered widget).
- **View:** non-PA → 403; PA GET → 200 with the SSO tab + redirect URI in the response; valid POST
  → 302 to `?tab=sso` + success message + row mutated; invalid POST → 200 re-render with errors,
  **no** mutation; GET on the action URL → 302 to `?tab=sso`.
- **Integration with the login page:** after an enabled save, the login page renders the
  "Continue with {name}" button (`get_providers` non-empty); after a disabled save, it does not.
- **e2e (real gestures):** PA fills the SSO form, enables, saves; assert the success state, then
  load the login page and assert the SSO button is present. (Drive the real click path — no
  `page.evaluate` shortcut.)

---

## Definition of Done (Phase 5d)

- A Platform Admin configures the institution's OIDC provider **entirely from
  `/manage/settings/?tab=sso`** — display name, issuer/discovery URL, client id, client secret —
  with **no** Django-admin access.
- An **Enabled** toggle shows/hides the login "Continue with …" button by attaching/detaching the
  current `Site`; **disabling preserves** the stored client secret.
- The **client secret is write-only**: it never appears in page source; a blank field keeps the
  saved secret, a typed value replaces it; the UI indicates whether a secret is on record.
- The **redirect URI** (`…/accounts/oidc/sso/login/callback/`) is displayed for the PA to register
  with their IdP.
- Enabling an **incomplete** config, or a **non-https** issuer, is rejected with clear field errors;
  nothing partial is saved.
- The view is **PA-permission-gated** and uses **PRG**; the tab is styled to match Branding/Access/
  Uploads and **verified light/dark/mobile**.
- EN + **PL** strings present and compiled (`.mo`); fuzzy flags cleared and PL msgids verified.
- `uv run pytest` green (existing suite + new SSO-config tests + e2e); `uv run ruff check .` and
  `uv run ruff format --check .` pass; `uv run python manage.py makemigrations --check --dry-run`
  **clean (no model changes)**; `manage.py check` clean.

**Out of scope (later):** multiple providers, SAML, live connection/discovery test, role-bearing
SSO provisioning, provider-specific allauth apps.
