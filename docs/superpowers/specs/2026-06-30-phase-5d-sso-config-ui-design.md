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

The JIT-provisioning *runtime* (the adapter, gating, not-provisioned page) is unchanged. The
SSO sign-in **affordances**, however, are surfaced in **two** places today with **divergent**
visibility logic, and 5d must reconcile them with the new toggle (see §4): the **login page**
(`templates/account/login.html`, site-aware via `{% get_providers %}`) and the **landing page**
(`templates/core/landing.html`, gated by `core/views.landing`'s non-site-aware
`sso_enabled = app is not None`). 5d changes **how the `SocialApp` row is created/edited** *and*
makes every entry point honor the enable toggle.

## Scope boundary (decided during brainstorming, 2026-06-30)

**In scope (5d):**
- A **single-provider**, edit-in-place SSO config form backed by allauth's existing `SocialApp`
  model (`provider="openid_connect"`). **No new model, no migration.**
- A new **"SSO" tab** in the existing `/manage/settings/` surface (4th tab beside
  Branding / Access / Uploads), reusing Phase 5c's shared template + per-tab POST action pattern.
- An explicit **"Enabled" toggle** distinct from the credentials: off = every SSO sign-in
  affordance hidden but client id / secret / issuer retained; on = shown. The toggle's single
  mechanism is the `SocialApp.sites` M2M (current `Site` attached ⇔ enabled). **Both SSO entry
  points are made to honor it:** the login page already does (site-aware `{% get_providers %}`),
  and 5d updates the **non-site-aware** landing-page button (`core/views.landing`) to gate on Site
  membership (see §4). The `user_settings` linked-account badge is **intentionally not** gated (it
  reflects the signed-in user's existing link, not whether new logins are enabled — §4).
- **Adopt, never duplicate, the existing OIDC row:** an install that configured SSO via Django
  admin under 0c‑2 already has a `SocialApp` (often with a blank `provider_id`). 5d's load and save
  must resolve to **that same row** and canonicalize it, never create a second one (see §1).
- **Write-only client secret:** the stored secret is never rendered back to the browser; a blank
  secret field preserves the existing secret, a typed value replaces it.
- A read-only, copyable **redirect URI** display (the row's effective callback, typically
  `…/accounts/oidc/sso/login/callback/`) for the PA to register with their IdP.
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
| Settings views | `institution/views_manage.py` *(modified)* | Add `"sso"` to `TABS`; thread `request` into `_settings_context` so it builds the SSO sub-context for **every** tab render (the SSO panel is always present, see §3); new `settings_sso` POST action (PRG) delegating to the service. |
| Landing/settings SSO surfaces | `core/views.py` *(modified)*; `templates/core/landing.html` *(unchanged markup)* | Gate `landing`'s `sso_enabled`/`sso_login_url` on Site membership + the row's effective `provider_id`, so the toggle governs the landing button too (§4). |
| URL | `institution/urls.py` *(modified)* | `manage/settings/sso/` → `name="settings_sso"`. |
| Templates | `templates/institution/manage/settings.html`, `_tabs.html` *(modified)*; `templates/institution/manage/_sso_tab.html` *(new)* | Fourth tab + the SSO form panel (enable toggle, 4 fields, "secret saved" hint, redirect-URI block). |
| Styles | `static/institution/settings.css` *(modified)* | Any SSO-specific styling (redirect-URI block, toggle) reusing the existing `settings__*` classes. |
| Tests | `tests/test_sso_config.py` *(new)*; e2e under existing e2e dir | Service, form, view, redirect-URI, enable/disable; one e2e. |

---

## 1. The config service (`accounts/sso_config.py`)

A small module isolating every read/write of the allauth `SocialApp` + `Site`, so the form and
view never query allauth models directly. Constants:

```
OIDC_PROVIDER    = "openid_connect"  # allauth provider key — the single-provider invariant
OIDC_PROVIDER_ID = "sso"             # default slug for a NEW row → stable redirect URI
```

The single-provider invariant is "the one row with `provider="openid_connect"`". `OIDC_PROVIDER_ID`
is the **default `provider_id` for a freshly created row** (so a clean install gets a stable
`…/oidc/sso/…` callback), **not** a key the load/save paths filter on — they key on `provider`
alone so they always resolve the *same* row, including a legacy 0c‑2 row whose `provider_id` is
blank or different.

**`effective_provider_id(app)` helper** — **`None`-tolerant:**
`(app.provider_id if app else "") or OIDC_PROVIDER_ID`. It must accept `app is None` (the
fresh-install case) and return the `"sso"` default, because `redirect_uri` is called with the loaded
app on **every** settings render — including before first save when `load_sso_app()` is `None` (a
plain `app.provider_id` would `AttributeError` and 500 the index). The callback/login URLs and the
displayed redirect URI are built from this. **It deliberately falls back to the `"sso"` constant —
NOT to `app.provider`** (`"openid_connect"`) the way `core/views.py`'s existing
`effective_provider = app.provider_id or app.provider` does. The two are similar but **not
identical**: for a legacy **blank**-slug row *before* the first 5d save they diverge (`"sso"` here
vs `"openid_connect"` there). The `"sso"` fallback is the correct one because `save_sso_config`
**canonicalizes** a blank slug to `"sso"` (step 1), so the URI the PA registers equals the post-save
callback allauth will serve. After any save the stored `provider_id` is non-blank, the fallback no
longer fires, and the helper just echoes the stored slug.

**Functions:**

- `load_sso_app() -> SocialApp | None` —
  `SocialApp.objects.filter(provider=OIDC_PROVIDER).order_by("pk").first()`. Returns `None` when SSO
  has never been configured. `order_by("pk")` is **deterministic and matches the existing
  `core/views.py` login-button query**, so the config UI always reads the *same* row the landing
  button renders (no split-brain if a stray duplicate exists).
- `is_enabled(app, site) -> bool` — `app is not None and app.sites.filter(pk=site.pk).exists()`.
- `redirect_uri(request, app) -> str` — `request.build_absolute_uri(reverse(
  "openid_connect_callback", kwargs={"provider_id": effective_provider_id(app)}))`. Built from the
  request so scheme+host are correct behind the deployment's proxy, and from the row's **effective**
  `provider_id` so the displayed URI matches the callback allauth actually serves for a legacy row.
  **Deployment caveat:** `build_absolute_uri` reports `http://` unless TLS terminates in-process or
  `SECURE_PROXY_SSL_HEADER` is configured, so the displayed/copied callback only reads `https://`
  when the deploy's proxy SSL header is set (the prod settings should ensure this); flag this in a
  one-line help note near the redirect-URI block so a PA doesn't register an `http://` callback.
  **Note (version-pinned, verified):** on the installed **allauth 65.18.0**, `openid_connect` mounts
  a **single parametrized** pattern `oidc/<provider_id>/login/callback/`
  (name `openid_connect_callback`) at import time — **not** a per-configured-app route — so
  `reverse("openid_connect_callback", kwargs={"provider_id": "sso"})` resolves with **zero**
  `SocialApp` rows and the URI renders before first save (using the `"sso"` default). A service test
  pins this (asserts `redirect_uri(request, None)` resolves with no rows — see Testing); if a future
  allauth upgrade made the route per-app, that test fails loudly rather than 500ing the live page.
- `save_sso_config(*, name, server_url, client_id, client_secret, enabled, site) -> SocialApp | None`
  — inside `transaction.atomic()`:
  1. **Adopt-or-create + canonicalize.** `app = load_sso_app()`; if `None` **and** there is nothing
     to persist — the **no-op condition**, defined exactly as `not enabled AND name == "" AND
     server_url == "" AND client_id == "" AND client_secret == ""` (all four input fields empty) —
     **return `None` without creating a row** (a blank disabled Save is a no-op — see Error
     handling). Note: a disabled draft with **any** one field filled (even just `name`) is **not** a
     no-op — it persists, per §2's "save a partial draft while disabled". Otherwise
     `app = app or SocialApp(provider=OIDC_PROVIDER)`; if `app.provider_id` is **blank**, set it to
     `OIDC_PROVIDER_ID` (`"sso"`). A legacy row with a **non-blank** `provider_id` keeps it (so any
     existing `SocialAccount` rows keyed on that value still resolve — re-stamping is limited to the
     blank case, which is already non-functional since `reverse(…)` needs a non-empty slug).
  2. Set `app.name = name`, `app.client_id = client_id`; merge issuer into JSON settings:
     `app.settings = {**(app.settings or {}), "server_url": server_url}`.
  3. **Secret:** set `app.secret = client_secret` **only if** `client_secret` is non-empty;
     otherwise leave the stored secret untouched. (The form passes `""` when the PA left it blank.)
  4. `app.save()`.
  5. **Enable toggle:** `app.sites.add(site)` if `enabled` else `app.sites.remove(site)`
     (idempotent; the M2M is the single source of "live", credentials are preserved on disable).
  6. Return `app`.

  The form's `clean` guarantees `save_sso_config` is only called with a complete-enough payload when
  `enabled` (see §2), so the service does not re-enforce the enable-completeness rule; its only
  self-guard is the **blank-disabled no-op** in step 1, so a never-configured install that Saves an
  empty disabled form still has **no** `SocialApp` row.

The current `Site` is resolved by the **caller** (view) via
`django.contrib.sites.shortcuts.get_current_site(request)` and passed in, keeping the service free
of request coupling. (`SITE_ID = 1` is set; 0c‑2 ties the `SocialApp` to the Site.)

## 2. The form (`accounts/forms.py` → `SsoForm`)

A plain `forms.Form` (not a `ModelForm`: `settings` is JSON, `sites` is M2M, and the secret is
write-only — none map cleanly to `ModelForm` fields).

**Constructor contract:** `def __init__(self, *args, app=None, **kwargs)` — pop `app` (the loaded
`SocialApp` or `None`) **before** `super().__init__(*args, **kwargs)` and store it on the instance,
so `clean` can consult `self.app.secret` for the stored-secret completeness check. The view passes
`app=load_sso_app()` on both the bound (POST) and unbound (GET/re-render) constructions.

**Fields** (all labels/help via `gettext_lazy` — module-level form text must be **lazy**, per the
eager-gettext-froze-labels gotcha):

| Field | Definition |
|---|---|
| `enabled` | `BooleanField(required=False)` — the live toggle. |
| `name` | `CharField(required=False, max_length=40)` — button label ("Continue with {name}"); `40` matches `SocialApp.name`'s column width. |
| `server_url` | `URLField(required=False, assume_scheme="https")` — issuer / discovery base. **`assume_scheme="https"` is required on Django 5.2** (verified 5.2.15): the default assumed scheme is still `http` (with a `RemovedInDjango60Warning`), so a bare `idp.example.test` would normalize to `http://…` and then fail the https check below — confusingly rejecting input that looked fine. Setting it makes a bare domain become `https://…` and pass. |
| `client_id` | `CharField(required=False, max_length=191)` — OIDC client id; `191` matches `SocialApp.client_id`'s column width. |
| `client_secret` | `CharField(required=False, max_length=191, widget=forms.PasswordInput(render_value=False))` — write-only; `191` matches `SocialApp.secret`'s column width. |

All fields are `required=False` at the field level; **completeness is enforced conditionally in
`clean`** (a disabled, partially-filled config is allowed; enabling demands a full config). This
keeps "save a draft while disabled" and "must be complete to go live" as one coherent rule.

**Initial seeding** (constructed by the view from the service, GET and error re-render):
- `enabled` ← `is_enabled(app, site)`; `name` ← `app.name`; `server_url` ←
  `app.settings.get("server_url", "")`; `client_id` ← `app.client_id`; all blank when `app is None`.
- `client_secret` initial is **always empty** (never seeded). The template separately shows
  whether a secret is on record (see §3) via the `sso_secret_saved` context flag (same name used in
  §3 and the template) — **not** via the field value, so the secret is never serialized to HTML.

**Validation (`clean`):**
- `server_url`, when non-empty, must be a **well-formed https URL**. `URLField` already validates
  URL shape; add a scheme check rejecting non-`https` (OIDC mandates TLS) with a clear error on the
  `server_url` field. **What `server_url` must contain (version-pinned, verified on allauth
  65.18.0, `openid_connect/provider.py:51` `wk_server_url`):** allauth appends
  `/.well-known/openid-configuration` to the stored value **iff** the value does not already contain
  `/.well-known/`. So a PA may enter **either** the **issuer base**
  (`https://idp.example.com`) **or** a full `.well-known` discovery URL — both work. **Trailing-slash
  trap:** allauth does a bare string concat, so a stored `https://idp.example.com/` becomes
  `https://idp.example.com//.well-known/openid-configuration` (double slash). To avoid it, the form
  **`.rstrip("/")`s the issuer in `clean`** before it is stored (a `.well-known` URL the PA pasted is
  left intact since it has no trailing slash). **Format validation always applies — even to a
  disabled draft:** the
  "save a partial draft while disabled" allowance below is about *completeness* (which fields may be
  empty), **not** *format* — a non-empty issuer must always be a valid https URL regardless of the
  toggle. (A wholly-empty `server_url` is fine while disabled.)
- **Enable-completeness:** if `cleaned_data["enabled"]` is true, then `name`, `server_url`, and
  `client_id` must all be non-empty, **and** a secret must be available — i.e. either a non-empty
  `client_secret` was typed **or** a secret is already stored (`bool(app and app.secret)`). The
  form is given the loaded `app` (or `None`) at construction so it can check the stored-secret case.
  Missing pieces raise field errors (`name`/`server_url`/`client_id`) or, for the secret,
  a `client_secret` field error: *"Enter the client secret to enable SSO."* This blocks a
  half-configured provider from going live.
- When `enabled` is false, no completeness is required (the PA may save a partial draft or blank
  everything); whatever is filled is persisted, the `Site` is detached. **Field-persistence
  asymmetry on an existing row:** a disabled save persists the **submitted** `name`/`server_url`/
  `client_id` *exactly as posted* — so actively **blanking** one of them on an existing row writes
  `""` to that column (only the **secret** is special-cased to "blank ⇒ keep existing"). A normal
  "just untick Enabled and Save" is safe because the GET-seeded form re-posts the current values; the
  wipe only happens if the PA clears a field on purpose. The DoD's "disabling preserves the secret"
  promise is therefore secret-specific by design, not a guarantee about the other columns.

**No secret in the form's cleaned output beyond what was typed:** `clean` does not read or copy the
stored secret into `cleaned_data`; the "keep existing" behavior lives entirely in the service
(blank ⇒ untouched).

**Two consequences of write-only + `render_value=False`, called out so neither reads as a bug:**
- **No in-UI secret *clear*.** Blank-keeps / typed-replaces gives no way to *remove* a stored secret
  through this form (even blanking everything while disabled preserves it, per §1 step 3). This is
  **intentional / out of scope** for 5d — rotating to a no-secret state is a rare admin action and
  remains available via Django admin. (A future "Clear secret" affordance could be added; not now.)
- **Typed secret is dropped on an invalid re-render.** Because `render_value=False`, if the PA types
  a new secret *and* another field is invalid (e.g. non-https issuer), the re-rendered password field
  is blank and the secret must be re-entered. This is the secure-by-design tradeoff (never echo the
  secret); the `_sso_tab.html` "secret saved" hint area should also carry a re-render note like
  *"Re-enter the client secret if you were changing it."* when the bound form has errors.

## 3. Views, URL & template

**`institution/views_manage.py`** (follows the 5c pattern exactly):
- `TABS = ("branding", "access", "uploads", "sso")`.
- **`_settings_context` gains a required `request` first parameter** —
  `_settings_context(request, inst, active_tab, *, branding=None, access=None, uploads=None, sso=None)`.
  Because `settings.html` renders **all four** tab panels on every response (inactive ones merely
  `hidden`), the SSO sub-context must be present on the GET index **and** on every invalid-POST
  re-render of the *other* tabs. So `_settings_context` always resolves `app = load_sso_app()` and
  `site = get_current_site(request)`, builds `sso or SsoForm(initial={...}, app=app)`, and adds
  `sso_secret_saved = bool(app and app.secret)` and `sso_redirect_uri = redirect_uri(request, app)`.
  **`_action` is updated to thread `request` through** (`_settings_context(request, inst, tab, ...)`),
  and the GET `settings` view passes `request` likewise. (The existing three forms are still seeded
  from `Institution`; SSO is seeded from the service — same shape, different source.)
- New action view `settings_sso(request)`: `@login_required` +
  `@permission_required("institution.change_institution", raise_exception=True)` (same guard as the
  other tabs — the PA has it). GET → redirect to the settings index via the existing
  `_index_url("sso")` helper (`reverse("institution:settings") + "?tab=sso"`), exactly like the other
  action views (POST-target contract). POST → bind `SsoForm(request.POST, app=load_sso_app())`; if
  valid, call `save_sso_config(**{k: form.cleaned_data[k] for k in
  ("name", "server_url", "client_id", "client_secret", "enabled")}, site=get_current_site(request))`.
  **The payload MUST come from `form.cleaned_data`, not `request.POST`** — the two `clean`-stage
  normalizations (the `assume_scheme="https"` rescheme and the trailing-slash `.rstrip("/")`) live
  only in `cleaned_data`; reading raw POST would silently store `http://…` and a double-slash
  discovery URL, defeating both §2 fixes. Then `messages.success(request, _("SSO settings saved."))`
  **only when `save_sso_config(...)` returned a non-`None` app** (so the blank-disabled no-op doesn't
  falsely claim a save — show nothing, or an `_("Nothing to save.")` info message, on the `None`
  return), and redirect to `?tab=sso` (PRG). If invalid, load `inst = Institution.load()` (needed by
  `_settings_context` to seed the three sibling ModelForms — `settings_sso` does **not** go through
  the shared `_action` helper) and re-render via `_settings_context(request, inst, "sso", sso=form)`.

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
    `help_text` + `.errors`, same markup as `_access_tab.html`). The **Issuer** field's `help_text`
    must steer the PA to the issuer base, e.g. *"Your IdP's issuer base URL, e.g.
    `https://idp.example.com`. The `/.well-known/openid-configuration` discovery path is added
    automatically (you may also paste a full discovery URL)."* (matches the verified §2 append
    behavior; avoids the PA guessing from the bare "Issuer / discovery URL" label).
  - **Client secret** field; directly above/below it, when `sso_secret_saved`, a
    `settings__help` line: *"A client secret is saved. Leave blank to keep it; enter a value to
    replace it."* When not saved: *"Enter the client secret from your IdP."*
  - **Redirect URI block** — a read-only, copyable display of `{{ sso_redirect_uri }}` with a
    `settings__help` note: *"Register this redirect URI with your identity provider."* (Plain
    selectable text / read-only input; no JS clipboard dependency required, though a small
    copy affordance is acceptable if it matches the design system.) **Also include the scheme
    caveat note mandated by §1** — e.g. *"If this shows `http://`, your deployment's HTTPS proxy
    header isn't configured; register the `https://` form."* — so §1 and §3 agree.
  - `settings__actions` → `<button class="btn">{% trans "Save SSO settings" %}</button>`.

**Styling.** Reuse `settings__form/section/field/label/help/actions`. Add minimal CSS only for the
redirect-URI block and the toggle if the existing classes don't cover them. **Verify light + dark +
mobile via throwaway Playwright screenshots** (delete-after-review) before shipping, per house rule
(every view ships styled).

## 4. SSO entry-point surfaces — making the toggle authoritative

The enable toggle = current `Site` ∈ `SocialApp.sites`. SSO is surfaced in three places, with
**different** existing visibility logic; 5d reconciles them so "disabled" hides SSO **everywhere a
new login could start**, while leaving an already-linked user's badge alone:

| Surface | Today | After 5d |
|---|---|---|
| **Login page** (`templates/account/login.html`) | Site-aware: `{% get_providers %}` → allauth's `SocialApp.objects.on_site` | **No change** — already honors the toggle. |
| **Landing page** (`core/views.landing` → `templates/core/landing.html`) | **Non-site-aware:** `sso_enabled = app is not None`; `sso_login_url` from `app.provider_id` (blows up on a blank slug) | **Gate on Site membership.** `app = load_sso_app()`; `sso_enabled = is_enabled(app, get_current_site(request))`; keep the **existing** `reverse("openid_connect_login", kwargs={"provider_id": …})` (the current `core/views.py:53` call) but feed it `effective_provider_id(app)` instead of the bare `app.provider_id`. §1 supplies the shared **row resolver + slug helper** (`load_sso_app`/`effective_provider_id`), **not** a login-URL builder — `redirect_uri` is the *callback*, not the button href. Guard `sso_login_url` to `None` when `not sso_enabled`. |
| **User-settings badge** (`core/views.user_settings`) | Non-site-aware: shows the signed-in user's linked-account label whenever an OIDC app exists | **Intentionally not gated on the toggle.** The badge states a *fact about this user's account* (they have an SSO-linked identity), which remains true after the PA disables new SSO logins. Left as-is functionally; its existing `effective_provider = app.provider_id or app.provider` resolution keeps working because after a 5d save the slug is non-blank (the only case where its `app.provider` fallback would differ from §1's `"sso"` fallback is a blank-slug row, which 5d canonicalizes away). Documented here so the asymmetry is a decision, not an oversight. |

This is why `load_sso_app()`/`effective_provider_id()` live in `accounts/sso_config.py` and not
inline in the view — both `core/views.landing` and the settings surface import the **one** resolver,
so they can never select different rows or slugs.

**Transient legacy edge (documented, not a 5d bug):** a 0c‑2 install whose `SocialApp` has the
`Site` attached **but a blank `provider_id`** becomes `is_enabled == True` the moment 5d deploys, so
the landing page renders a "Continue with SSO" button at the `"sso"` slug — yet the row's stored
`provider_id` stays blank until the PA saves once, so a click can't resolve the `SocialApp` and
errors. This window is harmless in practice: pre-5d that same surface **500'd** (blank slug →
`NoReverseMatch`), and any install where SSO actually *worked* already had a **non-blank** slug
(so it's unaffected). The first PA save canonicalizes the slug and closes the window. Flagged so it
reads as a known transient, not a regression.

## Data flow

**Configure & enable:** PA opens `/manage/settings/?tab=sso` → GET renders `SsoForm` seeded from
the `SocialApp` (or blank), shows redirect URI + "secret saved?" hint → PA fills fields, checks
**Enabled**, submits → `settings_sso` POST → `clean` passes completeness → `save_sso_config` adopts
(or creates + canonicalizes) the row, stores name/issuer/client_id/secret, **adds** the Site →
redirect `?tab=sso` with success message → **both** entry points now show SSO: the login page's
site-aware `{% get_providers %}` returns the provider, and `core/views.landing`'s now-site-aware
`sso_enabled` is true → "Continue with {name}" / "Continue with SSO" buttons appear.

**Disable (keep secret):** PA unchecks **Enabled**, submits → service **removes** the Site from
`app.sites`; `name/client_id/secret/settings` untouched → the login **and** landing buttons both
disappear (both gate on Site membership after §4); the user-settings linked-account badge is
unaffected by design; re-enabling later needs no re-entry of the secret.

**Rotate secret:** PA types a new value in **Client secret**, submits → service overwrites
`app.secret`. Leaving it blank on any later save preserves it.

## Error handling

- **Invalid submit** (enabling while incomplete, non-https issuer) → form re-renders on the `sso`
  tab with field-level errors; nothing saved (no partial write — the single `save_sso_config` call
  is gated on `form.is_valid()`).
- **Non-PA access** → `permission_required(raise_exception=True)` → 403 (same as the other tabs).
- **GET on the action URL** → redirect to `_index_url("sso")`
  (`reverse("institution:settings") + "?tab=sso"`), the same index the post-PRG save redirects to
  (method contract).
- **Secret never leaks** — the stored secret is not seeded into the field nor placed in
  `cleaned_data`/context; only `secret_saved` (a boolean) reaches the template.
- **No row yet** — `load_sso_app()` returns `None`; the form is all-blank, the redirect URI still
  renders (route exists at import time, using the `"sso"` default slug), and the first save that has
  something to persist creates the row.
- **Blank disabled Save** — submitting the SSO tab with the **no-op condition** (`not enabled` AND
  `name`/`server_url`/`client_id`/`client_secret` **all four** empty) when no row exists is a
  **no-op**: `save_sso_config` returns `None` and creates nothing (step 1 guard), so neither the
  login nor the landing button is offered from an empty stub row. A disabled draft with any single
  field filled persists instead (§2).
- **Legacy row adoption** — an SSO install configured via Django admin under 0c‑2 (often blank
  `provider_id`) is **adopted** by the first save, not duplicated: load/save both key on `provider`,
  and a blank `provider_id` is canonicalized to `"sso"` (a non-blank legacy slug is preserved).

## Testing (no live IdP)

`tests/test_sso_config.py` (+ an e2e in the existing e2e suite). No network; no DB-layer mocking
(project rule). Use a fresh `Site`/`SocialApp` per test.

- **Service:** `save_sso_config` creates the row with `provider="openid_connect"`,
  `provider_id="sso"` on a clean install; round-trips name/issuer (in `settings["server_url"]`)/
  client_id; **secret kept** when `client_secret=""`, **replaced** when non-empty; `enabled=True`
  adds the Site, `enabled=False` removes it; `redirect_uri(request, app)` ends with
  `/accounts/oidc/sso/login/callback/`; `is_enabled` reflects Site membership.
- **Zero-row URL linchpin:** with **zero** `SocialApp` rows, **both** `reverse("openid_connect_callback",
  kwargs={"provider_id": "sso"})` (via `redirect_uri(request, None)`, ending
  `/accounts/oidc/sso/login/callback/`) **and** `reverse("openid_connect_login",
  kwargs={"provider_id": "sso"})` (the landing-button route) resolve without `NoReverseMatch` — pins
  the allauth import-time parametrized-route assumption (§1/§4) for **both** routes the feature
  depends on, so an upgrade that broke either fails here, not in prod.
- **Normalization is end-to-end (view → stored value):** a valid enabled POST with
  `server_url = "idp.example.test/"` (bare host, trailing slash) results in
  `settings["server_url"] == "https://idp.example.test"` (rescheme'd by `assume_scheme`, slash
  stripped) — proves the view passes `form.cleaned_data`, not raw POST (regression guard for §3's
  payload-source rule).
- **Row adoption / canonicalization:** a pre-existing `openid_connect` `SocialApp` with **blank
  `provider_id`** is **adopted** (no second row created — assert `SocialApp.objects.count()` stays 1)
  and its `provider_id` becomes `"sso"`; a pre-existing row with a **non-blank** `provider_id`
  (e.g. `"google"`) is adopted with its slug **preserved**, and `redirect_uri`/`effective_provider_id`
  reflect that slug; `load_sso_app()` and the landing-button query resolve the **same** row.
- **Blank-disabled no-op:** `save_sso_config` with `enabled=False` and all four inputs
  (`name`/`server_url`/`client_id`/`client_secret`) empty, with no existing row, returns `None` and
  creates nothing (`SocialApp.objects.count() == 0`). **Boundary:** the same call with **only `name`
  filled** (still disabled) **does** create a persisted draft row (asserts the no-op is all-four-empty,
  not "credentials only").
- **Form:** non-https `server_url` → error; `enabled=True` with a missing field → field error;
  `enabled=True`, no stored secret, blank `client_secret` → `client_secret` error; `enabled=True`
  with a stored secret + blank `client_secret` → **valid** (keep-existing); `enabled=False`
  partial/blank → valid; the field never renders the stored secret (assert the secret string is
  absent from the rendered widget). The `app=` kwarg drives the stored-secret branch.
- **View:** non-PA → 403; PA GET → 200 with the SSO tab + redirect URI in the response; valid POST
  → 302 to `?tab=sso` + success message + row mutated; invalid POST → 200 re-render with errors,
  **no** mutation; GET on the action URL → 302 to `?tab=sso`. Also assert the SSO sub-context
  (`sso_redirect_uri`) is present on an **invalid POST to another tab** (e.g. access) — the panel is
  always rendered.
- **Both entry points honor the toggle:** after an enabled save, **both** the login page
  (`get_providers` non-empty / button present) **and** the landing page (`sso_enabled` true / SSO
  link present) show SSO; after a disabled save, **both** hide it. (Regression guard for the
  non-site-aware landing button — §4.) **Sequencing matters:** the save requires the PA to be
  authenticated, but `core/views.landing` redirects authenticated users to `/home` (`core/views.py:45`)
  and the login page is an anonymous surface — so after each POST the test must **switch to an
  unauthenticated client** (`client.logout()` or a fresh `Client()`) before GETting landing/login
  and asserting `sso_enabled` / `get_providers`. Apply symmetrically for the disabled-save assertion.
- **e2e (real gestures):** PA (authenticated) fills the SSO form, enables, saves; assert success;
  then — in a **logged-out / anonymous browser context** — load the **landing page** and assert the
  SSO button is present; re-authenticate, disable via the form; back in the anonymous context reload
  landing and assert the button is gone. (Drive the real click path — no `page.evaluate` shortcut.
  Landing is chosen because it was the broken surface, and it is anonymous-visible so the button
  actually renders.)

---

## Definition of Done (Phase 5d)

- A Platform Admin configures the institution's OIDC provider **entirely from
  `/manage/settings/?tab=sso`** — display name, issuer/discovery URL, client id, client secret —
  with **no** Django-admin access.
- An **Enabled** toggle (current `Site` ∈ `SocialApp.sites`) shows/hides **every** SSO sign-in
  affordance — the login-page button **and** the landing-page "Continue with SSO" button (both
  site-aware after §4); the user-settings linked-account badge is intentionally unaffected.
  **Disabling preserves** the stored client secret.
- An install that previously configured SSO via Django admin (0c‑2) is **adopted, not duplicated**:
  load and save resolve the same `openid_connect` row, a blank `provider_id` is canonicalized to
  `"sso"` (a non-blank legacy slug preserved), and `SocialApp.objects.count()` never grows beyond 1.
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
