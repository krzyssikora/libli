# Phase 1b — Auth / login redesign (#15 + bounded-full auth surface)

*Design doc. Drafted 2026-06-18. Closes the last designed items of the Phase-1b
UX-review-triage backlog: **#15** (login page) plus the sibling auth screens that
already have accepted mockups, plus the small **#9b-i18n** carry-over.*

Companion docs: `docs/superpowers/specs/2026-06-16-phase-1b-ux-review-triage.md`
(the triage backlog), `docs/mockups/README.md` (accepted mockups).

---

## 1. Goal & scope

Replace the stock-allauth auth screens (which currently render inside the full app
top-bar shell, with raw `{{ form.as_p }}` on our own templates) with libli's
warm-teal **centered auth card**, built to the already-accepted mockups.

**In scope — "bounded-full":**

1. **Layout layer (built once):** a reusable centered auth-card layout that applies to
   every allauth *entrance* page, via an override of `account/base_entrance.html`.
2. **Hero pages — bespoke, to mockup fidelity:**
   - **Login** (#15) → `docs/mockups/identity-directions_V2-chosen.html` (the **V2 warm-teal** card).
   - **Signup** + **invite-accept** → `docs/mockups/auth-and-settings_accepted.html` (1.4).
   - **Password reset** (request + done + from-key + from-key-done) → same mockup (1.5).
   - **SSO-not-provisioned** → same mockup (1.3).
3. **Long-tail allauth entrance pages** (logout, verification_sent, account_inactive,
   reauthenticate, password_set, request_login_code, etc.): **inherit the centered
   layout automatically**; rely on allauth's default element markup + our base element
   styling so they read clean. **Explicit non-goal:** no bespoke per-page design, no
   overriding `allauth/elements/*`.
4. **`password_change`** (reached from settings, authenticated): stays in the full app
   shell; its form gets a styled card. Minor.
5. **#9b-i18n** carry-over: translate the builder/editor JS "this changed" notice to PL.

**Out of scope / non-goals:**

- No new models, migrations, or Python views. allauth supplies login/signup/reset views;
  `accept_invite` and `sso_not_provisioned` views already exist; chrome reuses existing
  `core:set_ui_language` / `core:set_theme`.
- No bespoke design or `allauth/elements/*` overrides for the long-tail pages (boundary
  that keeps "full" from ballooning into undesigned corner templates).
- No new auth *features* (no remember-me toggle UI unless allauth already emits it, no
  passkey/login-code UI work — those flags are off; their templates just inherit the layout).
- Brand **colours** remain Phase 5 (we consume the existing tokens only).

---

## 2. Background — current state (verified against the repo)

- `templates/allauth/layouts/base.html` is our override and is a one-liner:
  `{% extends "base.html" %}`. So **today every allauth page renders inside the full app
  top-bar** (`base.html`'s `.app-header` with brand, EN/PL switch, theme toggle, and an
  anonymous **"Log in" CTA** — which is redundant *on the login page itself*).
- Stock `account/login.html` extends `account/base_entrance.html` →
  `allauth/layouts/entrance.html` → `allauth/layouts/base.html`, and renders the form
  through allauth's `{% element %}` tag system.
- `account/base_entrance.html` is used **only by entrance (unauthenticated) pages**;
  manage pages use `account/base_manage.html`. Overriding `base_entrance.html` therefore
  targets exactly the screens we want and leaves authenticated pages alone.
- Our own auth templates are raw: `accounts/accept_invite.html` uses `{{ form.as_p }}`;
  `accounts/sso_not_provisioned.html` is a bare `<h1>`+`<p>`.
- The **design-system vocabulary already exists**: `core/static/core/css/tokens.css`
  defines `--primary`/`--accent`/`--surface-raised`/`--surface-sunken`/`--text-primary`/
  `--text-secondary`/`--text-tertiary`/`--border-default`/`--border-strong`/`--radius-*`/
  `--shadow-*`/`--space-*`, with a full **dark** override block. `app.css` defines `.btn`,
  `.btn--ghost`, `.btn--icon`, `.card`, `.alert`, the `.app-header` cluster, and the
  `.lang-switch` form. The V2 mockup's hardcoded hexes map 1:1 onto these tokens, so the
  new CSS is **pure-token, no hex**.

---

## 3. Architecture

### 3.1 Layout layer

**`base.html` refactor (DRY — one `<head>`, one pre-paint script).**
Introduce three template hooks so an auth layout can restyle the chrome without
duplicating the head or the no-flash script:

- Wrap the existing `<header class="app-header">…</header>` in `{% block header %}…{% endblock %}`.
- Add `{% block body_class %}{% endblock %}` to the `<body>` tag.
- Add `{% block main_class %}app-main{% endblock %}` to the `<main>` tag.

These are additive: existing pages render byte-identically (default block contents are the
current markup). The messages loop, stylesheet links, `{% brand_vars %}`, pre-paint script,
and `ui.js` all stay in `base.html` unchanged.

**`templates/account/base_entrance.html` (new override).**

```
{% extends "base.html" %}
{% block body_class %}auth{% endblock %}
{% block main_class %}auth-main{% endblock %}
{% block header %}
  <div class="auth-chrome">
    <!-- the existing lang-switch form (reused verbatim) -->
    <!-- the existing theme-toggle button (reused verbatim) -->
  </div>
{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/auth.css' %}">{% endblock %}
{% block content %}{% endblock %}
```

- The `auth` body class + `auth-main` switch the page from the standard `.app-main`
  max-width column to a **centered flex container** (min-height viewport, card centered).
- `.auth-chrome` is a minimal top-right cluster: only the EN/PL `lang-switch` form and the
  theme-toggle `button[data-theme-toggle]` (both reused verbatim from `base.html` so the
  existing `ui.js` + `set_theme`/`set_ui_language` endpoints keep working). **No brand
  link, no avatar, no "Log in" CTA** — the wordmark lives inside the card.

**`core/static/core/css/auth.css` (new).**
Token-only vocabulary, light + dark inheriting the existing token switch:

- `.auth-main` — centered flex, viewport-height, padding.
- `.auth-card` — `--surface-raised` bg, `--border-default`, `--radius-lg`, `--shadow-lg`,
  ~360–400px max-width, padding per mockup.
- `.auth-card__wordmark` (the `libli.` mark with `.brand__dot`), `.auth-card__title`
  ("Sign in to …"), `.auth-card__subtitle`.
- `.auth-field` + reuse a label/input pair (`.auth-label`, `.auth-input`) styled from
  tokens (input bg `--surface-sunken`, border `--border-strong`, `--radius-sm`).
- `.auth-divider` (the "or" rule), `.auth-sso` button (`--surface-sunken` face,
  `--border-strong`), `.auth-foot` (muted, accent link).
- `.auth-error` / field-error styling from `--danger` / `--danger-subtle`.
- `.auth-chrome` positioning.
- Base styling for allauth's **default element output** (plain `<input>`, `<button>`,
  `<h1>`, `<p>`, `<form>`, `<ul>`) **scoped within `.auth-card`** so the long-tail pages
  render clean without per-page work.

### 3.2 Hero templates (bespoke, mockup fidelity)

All extend `account/base_entrance.html` and fill `{% block content %}` with a single
`.auth-card`. Rendered as **plain HTML forms** (not allauth `{% element %}`), for full
markup control:

**`templates/account/login.html`** (V2 mockup, #15):

- `.auth-card__wordmark` → `libli<span class="brand__dot">.</span>`.
- Title `{% blocktranslate %}Sign in to {{ site_name }}{% endblocktranslate %}` where
  `site_name = site.name|default:"libli"` (from the `institution_branding` context
  processor, already global).
- Subtitle: "Welcome back — pick up where you left off."
- Form `method="post" action="{% url 'account_login' %}"`: `{% csrf_token %}`, the
  `redirect_field`, `form.non_field_errors`, and **manually rendered** `form.login` +
  `form.password` with `.auth-label` / `.auth-input` and per-field error rendering. If
  `form.remember` exists (allauth emits it only when `ACCOUNT_SESSION_REMEMBER=None`), it
  renders as a checkbox; otherwise omitted. (Confirm the field set against the bound
  `LoginForm` during implementation; render whatever fields are present rather than
  hardcoding.)
- Submit: "Sign in" (`.btn`, full width).
- **SSO block** — `{% load socialaccount %}` + `{% get_providers as socialaccount_providers %}`;
  if any, render the `.auth-divider` ("or") and, per provider, a `.auth-sso` anchor to
  `{% provider_login_url provider process='login' %}` labelled
  `{% blocktranslate %}Continue with {{ provider_name }}{% endblocktranslate %}` (+ the
  Google glyph mark from the mockup for the google/openid provider). Conditional, so a
  no-SSO institution shows no divider.
- **Footer** — if `site.signup_policy == "open"`: "No account? {link}sign up{/link}"
  (`account_signup`); else the static "No account? Ask your administrator." (`site` carries
  `signup_policy` via `get_site_config()`).

**`templates/account/signup.html`** → 1.4 card: same shell; render the allauth signup
form fields manually (email/username/password fields per the bound form). The mockup's
invite variant has email optional; the open-signup form requires a confirmed email — render
whatever fields the bound form exposes.

**`templates/account/password_reset.html`** (+ `password_reset_done.html`,
`password_reset_from_key.html`, `password_reset_from_key_done.html`) → 1.5: same shell,
email field / new-password fields / confirmation messages as appropriate.

**`templates/accounts/accept_invite.html`** — replace `{{ form.as_p }}` with the card +
manually rendered fields. Keeps its existing view/context (`email`, `form`).

**`templates/accounts/sso_not_provisioned.html`** — restyle into the card (1.3): heading +
explanatory copy + a "Back to sign in" link. Keeps its existing view.

### 3.3 Long-tail entrance pages

`logout.html`, `verification_sent.html`, `account_inactive.html`, `password_set.html`,
`reauthenticate.html`, `request_login_code.html`, `confirm_login_code.html`, etc. are **not
overridden**. They extend allauth's `base_entrance.html` → now our centered layout → so they
appear in the card automatically. `auth.css`'s scoped element styling (§3.1) makes allauth's
default `{% element %}` output (buttons/inputs/headings) read clean. We add **no bespoke
markup** for these. If a specific one looks broken in manual smoke, the fix is a CSS rule in
`auth.css`, not a template.

### 3.4 `password_change`

Authenticated, reached from `/settings/`. Leave it on allauth's manage layout (full app
shell). Give its form a `.card` wrapper + our input styling so it matches the settings
aesthetic. No centered-entrance treatment (the user is logged in and wants the nav).

### 3.5 #9b-i18n (separate, parallel task)

The JS notice in `courses/static/courses/js/builder.js` (and `editor.js`) is a JS string
literal, which `makemessages` never extracts. **Normalize** both call sites to the **same
wording as the already-translated server variant** ("…reloaded to the latest.") so PL gets
**one** msgid, then feed the translated string into the DOM via a `data-msg-*` attribute on
the builder/editor root (rendered with `{% trans %}`), read in JS with an English fallback —
**the exact pattern WS2 already established** for `builder.js`'s conflict/illegal/network
notices (`data-msg-*` on `.builder`). Add the PL translation; recompile. Touches the two JS
files, their host templates, and `locale/pl/LC_MESSAGES/django.po`/`.mo`.

---

## 4. Data flow & dependencies

- **No new views.** allauth's `LoginView`/`SignupView`/`PasswordResetView` already wired;
  our `accept_invite` / `sso_not_provisioned` views unchanged.
- **Context already available** on allauth pages: `site` (name/logo/signup_policy via
  `institution_branding` + `get_site_config()`), `LANGUAGE_CODE`, theme vars, `languages`
  (for the lang-switch) — all from existing global context processors that run on every
  request. *Verify during implementation* that `languages`/`site`/theme context is present
  on the allauth-rendered request (they are global context processors, so they should be);
  if any is missing, that's a context-processor registration check, not new code.
- **SSO** uses allauth's `socialaccount` template tags directly — no dependency on the
  landing view's `sso_login_url`/`sso_enabled` context.
- **Endpoints reused:** `core:set_ui_language`, `core:set_theme`, `account_login`,
  `account_signup`, `openid_connect_login` (via `provider_login_url`).

---

## 5. Error handling & edge cases

- **Form errors** render with `.auth-error` (non-field) + per-field error lists, styled,
  no-JS. Plain POST round-trips work with JS disabled.
- **No SSO provider configured** → no divider, no SSO button (conditional on
  `get_providers`).
- **`signup_policy` ≠ open** → footer shows static "Ask your administrator", no signup link.
- **Theme/lang pre-paint** is unchanged (still served by `base.html`'s `<head>`), so the
  centered pages get no-flash theming for free.
- **Anonymous-only chrome:** `.auth-chrome` deliberately omits the avatar/account menu and
  the "Log in" CTA (entrance pages are anonymous; the CTA would be self-referential).
- **`site.name` empty** → title falls back to "libli".
- **Long-tail page regressions** are visual-only and CSS-fixable; functionally these pages
  keep allauth's behavior untouched.

---

## 6. Testing strategy

- **`tests/test_e2e_auth.py`** (Playwright, `-m e2e`, reuses the established harness):
  - Login page renders the card: brand wordmark, "Sign in to {institution}", both fields,
    Sign-in button.
  - Renders correctly in **light and dark** (theme toggle / pref).
  - **EN↔PL switch works on the login page** (the corner lang-switch submits and the page
    re-renders Polish — guards that the minimal chrome kept the switch functional).
  - **SSO button** appears when an OIDC provider is seeded, links to the provider login URL;
    absent when none.
  - **Successful local login → dashboard** (end-to-end, proves the bespoke form posts to
    `account_login` correctly).
  - **Signup-link visibility** flips with `signup_policy` (open → link present; invite →
    "Ask your administrator", no link).
  - Selectors scoped past any header controls (the recurring libli gotcha).
- **Style-regression guard** (`tests/test_auth_styles.py`, mirrors
  `test_settings_styles.py` / `test_editor_styles.py`): `auth.css` defines the key
  `.auth-card` / `.auth-input` / `.auth-sso` / `.auth-divider` classes; the override
  templates resolve to ours and extend `account/base_entrance.html`.
- **Unit / integration:**
  - The resolved `account/login.html` is **our** override (template-name / marker assertion).
  - Footer link logic per `signup_policy` (render under open vs invite).
  - Sibling pages render **200 without `{{ form.as_p }}`** (signup, password_reset family,
    accept_invite, sso_not_provisioned).
  - `base.html` refactor: existing pages still render their header (a smoke assertion that
    `{% block header %}` default is intact).
- **i18n:** extend the PL gate (`tests/test_i18n_*`) to cover the new auth msgids; **#9b-i18n**
  unifies the JS-notice msgid (one entry, translated). New strings translated; catalog stays
  `0` untranslated / `0` fuzzy / `0` obsolete.
- **DoD gate:** full suite (`-m 'not e2e'`) + the auth e2e green; `ruff check` + `ruff format
  --check`; `manage.py check`; `makemigrations --check` (**no new migration**); `collectstatic`;
  `compilemessages -l pl`.

---

## 7. Task decomposition (for the plan — indicative)

1. `base.html` header/body/main block refactor + smoke test (existing pages unchanged).
2. `account/base_entrance.html` override + `auth.css` skeleton (layout + card + tokens) +
   style guard.
3. `account/login.html` bespoke (fields, errors, submit, footer gating) — the #15 core.
4. Login SSO block (allauth `socialaccount` tags, conditional, glyph).
5. `account/signup.html` + `accounts/accept_invite.html` (drop `form.as_p`).
6. `account/password_reset*.html` family + `accounts/sso_not_provisioned.html`.
7. Long-tail element styling pass in `auth.css` (logout/verification/etc. read clean) +
   `password_change` card.
8. #9b-i18n (normalize JS notice → `data-msg-*` + PL).
9. i18n extraction + PL translations + per-msgid gate.
10. Playwright `tests/test_e2e_auth.py` + DoD gate.

---

## 8. Open questions

None blocking. Two items to **confirm during implementation** (not design decisions):

1. The exact bound-form field set for `LoginForm` / signup / reset under our allauth 65.18
   config (render present fields rather than hardcoding).
2. That `site` / `languages` / theme context processors run on allauth-rendered requests
   (they are global; expected present — verify, don't assume).
