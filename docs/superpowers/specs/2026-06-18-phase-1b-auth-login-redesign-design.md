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
   every allauth *entrance* page, via an override of **`allauth/layouts/entrance.html`** (the
   verified common ancestor of all entrance pages — see §3.1; this is broader than
   `account/base_entrance.html` and is the only point that also catches `account_inactive`).
2. **Hero pages — bespoke, to mockup fidelity:**
   - **Login** (#15) → `docs/mockups/identity-directions_V2-chosen.html` (the **V2 warm-teal** card).
   - **Signup** + **invite-accept** → `docs/mockups/auth-and-settings_accepted.html` (1.4).
   - **Password reset** (request + done + from-key + from-key-done) → same mockup (1.5).
   - **SSO-not-provisioned** → same mockup (1.3).
3. **Long-tail pages, no bespoke markup** — split by their actual parent chain (§3.3):
   **Bucket A** (entrance chain: `verification_sent`, `account_inactive`, `reauthenticate`,
   `request_login_code`, `confirm_login_code`, …) inherit the **centered card** automatically;
   **Bucket B** (manage chain: `logout`, `password_set`, email mgmt) stay in the **full app
   shell** (correct — they're authenticated). Both rely on allauth's default element markup +
   our base styling so they read clean. **Explicit non-goal:** no bespoke per-page design, no
   overriding `allauth/elements/*`.
4. **`password_change`** (reached from settings, authenticated): manage chain → stays in the
   full app shell; its form gets a styled card. Minor.
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
  top-bar** (`base.html`'s `.app-header` with brand, EN/PL switch, theme toggle, avatar/account
  menu when authed, and an anonymous "Log in" CTA). Note the CTA is **already** suppressed on
  these routes — `ui_prefs` sets `hide_auth_cta` for `account_*` / `accounts:*` / `landing`
  (`core/context_processors.py:48`) and `base.html` guards it with `{% elif not hide_auth_cta %}`.
  So the reason to override the header is **not** the CTA but the rest of the full-width chrome
  (brand link, avatar menu, app-width layout) — which the centered card replaces wholesale.
- Stock `account/login.html` extends `account/base_entrance.html` →
  `allauth/layouts/entrance.html` → `allauth/layouts/base.html`, and renders the form
  through allauth's `{% element %}` tag system.
- The **entrance** (unauthenticated) pages and the **manage** (authenticated) pages descend
  from two different allauth layouts (`allauth/layouts/entrance.html` vs
  `allauth/layouts/manage.html`). §3.1 derives the precise override point from the verified
  parent chains: we override **`allauth/layouts/entrance.html`** (the entrance common ancestor),
  which targets exactly the entrance screens and leaves the authenticated manage pages alone.
- Our own auth templates are raw: `accounts/accept_invite.html` uses `{{ form.as_p }}`;
  `accounts/sso_not_provisioned.html` is a bare `<h1>`+`<p>`.
- The **design-system vocabulary already exists**: `core/static/core/css/tokens.css`
  defines `--primary`/`--accent`/`--surface-raised`/`--surface-sunken`/`--text-primary`/
  `--text-secondary`/`--text-tertiary`/`--border-default`/`--border-strong`/`--danger`/
  `--danger-subtle`/`--radius-*`/`--shadow-*`/`--space-*`, with a full **dark** override block. `app.css` defines `.btn`,
  `.btn--ghost`, `.btn--icon`, `.card`, `.alert`, the `.app-header` cluster, and the
  `.lang-switch` form. The V2 mockup's hardcoded hexes map 1:1 onto these tokens, so the
  new CSS is **pure-token, no hex**.

---

## 3. Architecture

### 3.1 Layout layer

**`base.html` refactor (DRY — one `<head>`, one pre-paint script).**
Introduce template hooks so an auth layout can restyle the chrome without
duplicating the head or the no-flash script:

- Wrap the existing `<header class="app-header">…</header>` in `{% block header %}…{% endblock %}`.
- Add `{% block body_class %}{% endblock %}` to the `<body>` tag and
  `{% block main_class %}app-main{% endblock %}` to the `<main>` tag.
- Add **`{% block extra_head %}{% endblock %}`** in `<head>` and
  **`{% block extra_body %}{% endblock %}`** just before `</body>`. **Why this matters:** the
  centered entrance layout (below) extends `base.html` directly, **bypassing**
  `allauth/layouts/base.html` — which is where allauth defines `extra_head`/`extra_body`. Some
  allauth templates emit into those blocks (e.g. `login.html`'s passkey/login-code `{% include %}`
  in `{% block extra_body %}`, MFA flows). Our `base.html` today defines only `extra_css`/
  `extra_js`, so **without these two blocks any allauth head/body plumbing is silently dropped.**
  Adding them is cheap and future-proofs login-code/passkey/MFA (those flags are off today, so it
  is not a live regression now — but the bridge must exist before any of them is enabled).

These are additive: existing pages render byte-identically (default block contents are the
current markup). Stylesheet links, `{% brand_vars %}`, pre-paint script, `ui.js`, and the
messages loop all stay in `base.html` unchanged.

**Override point — `templates/allauth/layouts/entrance.html` (the entrance common ancestor).**
The set of pages to center is wider than just `account/base_entrance.html`. Verified against
allauth 65.18 parent chains:

| page | chain | inherits entrance.html? |
|---|---|---|
| login / signup / password_reset* / request_login_code | → `account/base_entrance.html` → `allauth/layouts/entrance.html` | ✅ |
| confirm_login_code | → `base_confirm_code.html` → `base_entrance.html` → `entrance.html` | ✅ |
| reauthenticate | → `base_reauthenticate.html` → `base_entrance.html` → `entrance.html` | ✅ |
| **account_inactive** | → `allauth/layouts/entrance.html` **directly** (skips `base_entrance`) | ✅ |
| logout / password_set / email mgmt / password_change | → `…/base_manage.html` → `allauth/layouts/manage.html` | ❌ (manage shell — stays full-shell, see §3.3/§3.4) |

So the single common ancestor of **every entrance (unauthenticated) page** is
**`allauth/layouts/entrance.html`**. We override **that** (not `account/base_entrance.html`),
which centers every entrance page **including `account_inactive`**. We do **not** override
`account/base_entrance.html` — allauth's stock one extends our overridden `entrance.html`, so it
inherits for free. The existing `templates/allauth/layouts/base.html` override (`{% extends
"base.html" %}`) stays in place and continues to serve the **manage** chain in the full shell.

```
{# templates/allauth/layouts/entrance.html — overrides allauth's bundled one #}
{% extends "base.html" %}
{% load static i18n %}
{% block body_class %}auth{% endblock %}
{% block main_class %}auth-main{% endblock %}
{% block header %}
  <div class="auth-chrome">
    {# the existing lang-switch form + theme-toggle button, reused verbatim from base.html #}
  </div>
{% endblock %}
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'core/css/auth.css' %}">{% endblock %}
{# NO {% block content %} here — child pages (login.html etc.) fill base.html's content block directly #}
```

- **No content-wrapper block.** The override deliberately does **not** redeclare
  `{% block content %}`: child entrance templates override `content` wholesale (Django block
  semantics — a child block fully replaces the parent's), so a wrapper here would just be
  discarded. Centering is achieved purely by `auth-main` + `auth.css`, with the child's
  `.auth-card` as the flex child. (This resolves the round-2 "redundant empty content block" note.)
- **This override short-circuits the allauth entrance chain.** By extending `base.html`, entrance
  pages **bypass** `allauth/layouts/entrance.html`'s normal parent `allauth/layouts/base.html`
  (the allauth menu markup, allauth's own message rendering, the `extra_head`/`extra_body`
  plumbing). Those are **replaced** by `base.html`'s equivalents — hence the `extra_head`/
  `extra_body` bridge above, and `base.html`'s own messages loop (below) doing the message work.
- **`main_class` replaces, not augments.** `<main>` carries **only** `auth-main` on entrance
  pages — `.app-main`'s max-width-column rules are intentionally not applied (this is the desired
  full-bleed centering).
- **CSS loads additively.** auth.css is added via `{% block extra_css %}` with `{{ block.super }}`
  (so a child adding extra_css still composes and auth.css always loads). `reset.css` +
  `tokens.css` + `app.css` + `{% brand_vars %}` all still load. auth.css's `.auth-*` selectors
  must be scoped so they don't collide with `app.css`'s `.app-header`/`.app-main` (inert here
  anyway). auth.css goes in `extra_css`, **not** `extra_head` — leaving `extra_head`/`extra_body`
  free for allauth child templates.
- **Messages render above the card.** The Django `messages` loop lives in `base.html`'s `<main>`
  **but outside `{% block content %}`** (it precedes the content block). It is therefore retained
  and renders as a sibling flex child **above** the `.auth-card`. `.auth-main` must be a centered
  flex **column** so the alerts stack above the card while the card stays horizontally centered
  (see auth.css below); style `.alert` to read legibly in that column.
- `.auth-chrome` is a minimal top-right cluster: only the EN/PL `lang-switch` form and the
  theme-toggle `button[data-theme-toggle]` (both reused verbatim from `base.html` so the
  existing `ui.js` + `set_theme`/`set_ui_language` endpoints keep working). **No brand
  link, no avatar, no "Log in" CTA** — the wordmark lives inside the card.

**`core/static/core/css/auth.css` (new).**
Token-only vocabulary, light + dark inheriting the existing token switch:

- `.auth-main` — `display:flex; flex-direction:column; align-items:center; justify-content:center;`
  `min-height` ~viewport, padding. The **column** is what keeps the card centered while flash
  messages stack above it (pins the round-2 messages/centering ambiguity).
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

These keep their normal allauth template names (`login.html`, `signup.html`, …) — which now
resolve through our centered `entrance.html` override (§3.1) — and fill `{% block content %}`
with a single `.auth-card`. Rendered as **plain HTML forms** (not allauth `{% element %}`), for
full markup control:

**`templates/account/login.html`** (V2 mockup, #15):

- `.auth-card__wordmark` → `libli<span class="brand__dot">.</span>`.
- Title `{% blocktranslate %}Sign in to {{ site_name }}{% endblocktranslate %}` where
  `site_name = site.name` (from the `institution_branding` context processor, already
  global). **No `|default` needed:** `get_site_config()` coalesces `inst.name or
  "My Institution"` (`core/services.py`), so `site.name` is **never** empty — the configured
  institution name, or "My Institution" when unconfigured. (Do not write `|default:"libli"`;
  that branch is dead.)
- Subtitle: "Welcome back — pick up where you left off."
- Form `method="post" action="{% url 'account_login' %}"`: `{% csrf_token %}`, the
  `redirect_field`, `form.non_field_errors`, and a **per-field manual render of the named
  fields** `form.login` and `form.password` — each emitted explicitly (not via a generic field
  loop, since the mockup needs bespoke per-field label text + input styling) with `.auth-label`
  + `.auth-input` + its `{{ field.errors }}`. The remember checkbox is rendered behind
  `{% if form.remember %}` (allauth emits it only when `ACCOUNT_SESSION_REMEMBER=None`; our
  config does not set that, so expect it **absent** — the guard makes its presence/absence a
  no-op). **Graceful absence:** if a named field is unexpectedly missing, fall back to its
  allauth default render (`{{ form.login }}`) rather than `KeyError`-ing. Confirm the exact
  `LoginForm` field names against allauth 65.18 during impl (Open Q1).
- Submit: "Sign in" (`.btn`, full width).
- **SSO block** — `{% load socialaccount %}` + `{% get_providers as socialaccount_providers %}`;
  if any, render the `.auth-divider` ("or") and, per provider, a `.auth-sso` anchor to
  `{% provider_login_url provider process='login' %}` labelled
  `{% blocktranslate %}Continue with {{ provider_name }}{% endblocktranslate %}`. Glyph
  selection keys on **`provider.id == "openid_connect"`** (the only configured provider per
  WS4 — the generic OIDC provider) → render the mockup's Google glyph; any other/future
  `provider.id` falls back to a generic mark (or none). Conditional, so a no-SSO institution
  shows no divider.
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

> **Note (these two are NOT allauth routes):** both currently `{% extends "base.html" %}`
> directly — they are project `accounts:…` URLs, **not** allauth entrance routes, so they do
> **not** auto-inherit the centered layout. They must be **explicitly re-pointed** to
> `{% extends "allauth/layouts/entrance.html" %}` (our override) to pick up the centered card.
> Verify during impl that the entrance layout is safe for a non-allauth view — it only adds layout
> blocks + i18n/static load tags and assumes no allauth-only context (our override extends
> `base.html`, whose context
> is global), so this is expected to be safe; confirm by rendering both pages.

### 3.3 Long-tail pages — split by their actual parent chain

These are **not overridden** (no bespoke markup); they inherit styling from whichever layout
their chain resolves to. The round-2 review found the naïve "they all extend `base_entrance`"
list was wrong — the pages split into two buckets by **verified** allauth 65.18 parent chain:

**Bucket A — entrance chain → centered card (automatic via §3.1's `entrance.html` override):**
`verification_sent.html`, `account_inactive.html`, `reauthenticate.html`,
`request_login_code.html`, `confirm_login_code.html`, `password_reset_from_key_done.html`, and
the signup/login-code variants. (`account_inactive` qualifies **only because** we override
`allauth/layouts/entrance.html`, which it extends directly — overriding `account/base_entrance.html`
alone would have missed it.) `auth.css`'s scoped element styling (§3.1) makes allauth's default
`{% element %}` output (buttons/inputs/headings) read clean. If one looks broken in manual smoke,
the fix is a CSS rule in `auth.css`, not a template.

**Bucket B — manage chain → full app shell (unchanged, intentionally):** `logout.html`
(→ `base_manage.html`), `password_set.html` (→ `base_manage_password.html` → `base_manage.html`),
and the email-management pages. These extend `allauth/layouts/manage.html` → our existing
`allauth/layouts/base.html` override → full shell. **This is acceptable and intended:** all are
reached while **authenticated** (you have the nav), so the full shell is the right context — not
a bug to fix. We add no bespoke markup; the existing shell + `app.css` already style them.

**Explicit non-goal (boundary):** no bespoke per-page design and **no overriding
`allauth/elements/*`** for either bucket — that boundary keeps "bounded-full" from ballooning.

### 3.4 `password_change`

Authenticated, reached from `/settings/`. Its chain is the **manage** chain (Bucket B above) →
full app shell, so no special routing is needed. Give its form a `.card` wrapper + our input
styling so it matches the settings aesthetic. No centered-entrance treatment (the user is logged
in and wants the nav).

### 3.5 #9b-i18n (separate, parallel task)

**Current reality (verified against the repo):** `builder.js` +
`templates/courses/manage/builder.html` **already use** the `data-msg-*` pattern — a
`msg(key, fallback)` reader (`builder.js:107`) + `{% trans %}`-rendered
`data-msg-conflict`/`-illegal`/`-network` on the `.builder` root (shipped in the WS2
follow-up), with the wording **"This changed elsewhere — refreshed to the latest."** So
builder is **already i18n-wired** — it needs only a wording tweak, not the pattern. The
still-**hardcoded** literals are in **`editor.js:44`**
(`flash("This changed elsewhere — refreshed to the latest.")`) and **`media_picker.js:227`**
(`flash(root, "This changed elsewhere — please reload.")`) — neither has a `data-msg-*`
attribute or a reader.

**Catalog reality (verified):** `locale/pl/LC_MESSAGES/django.po` already contains **two
near-duplicate, both-translated** msgids: `"This changed elsewhere — reloaded to the latest."`
(line 95, the server-rendered 422 variant) and
`"This changed elsewhere — refreshed to the latest."` (line 616, the builder JS variant). The
#9b-i18n goal is to collapse these to **one**.

**Target:** converge every conflict notice on the single canonical msgid **"This changed
elsewhere — reloaded to the latest."** (the server variant, per the triage decision). Because
that msgid **already exists and is already translated**, converging on it adds **no** new
untranslated entry — it retires the duplicate. Work:

- **`editor.js` + its host template** — add a `{% trans %}`-rendered `data-msg-conflict` attr
  on the editor root + a `msg()`-style reader (mirroring `builder.js`); replace the bare literal.
- **`media_picker.js` + its host** — same pattern (or read the editor root's attr), replacing
  the "please reload" wording with the canonical one.
- **`builder.html` `data-msg-conflict` + `builder.js` fallbacks** — change "refreshed" →
  "reloaded" so they point at the surviving msgid.
- **Retire** the now-unused `"…refreshed to the latest."` msgid; confirm `"…reloaded to the
  latest."` keeps its PL translation; recompile `.mo`.

**Gate:** the PL catalog stays **0 untranslated / 0 fuzzy / 0 obsolete** (the retired msgid must
not linger as a `#~` obsolete entry). Touches `editor.js`, `media_picker.js`, `builder.js`,
their host templates, and `django.po`/`.mo`.

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
- **allauth view-supplied context the bespoke login form depends on.** `redirect_field`
  (the rendered `?next=` hidden input — preserves post-login redirect-to-intended-page) and
  `signup_url` are provided by allauth's `LoginView`, **not** by our global context processors.
  The bespoke `login.html` **must** keep emitting `{{ redirect_field }}` inside the form;
  dropping it silently breaks `?next=` redirects (a functional regression that the
  "render present fields" form-field guidance does **not** cover, since `redirect_field` is
  *context*, not a form field). Confirm the exact allauth-65.18 variable names during impl
  (Open Q3); if `redirect_field` is somehow absent, fall back to a hand-rolled
  `<input type="hidden" name="next" value="{{ redirect_field_value }}">`.
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
- **Anonymous-only chrome:** because the override replaces the whole `{% block header %}`, the
  avatar/account menu and the "Log in" CTA simply don't render — `.auth-chrome` re-adds only the
  lang-switch + theme toggle. (The CTA was already hidden on these routes via `hide_auth_cta`, so
  this isn't a new suppression — the override just doesn't reintroduce it.)
- **`site.name`** is never empty (`get_site_config()` coalesces to "My Institution"); the
  title shows the configured institution name, or "My Institution" when unconfigured. A login
  e2e/unit test asserting the title must expect the configured/"My Institution" value, **not**
  "libli".
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
  `.auth-card` / `.auth-input` / `.auth-sso` / `.auth-divider` classes; a rendered login page
  carries the centered layout markers (`body.auth` / `main.auth-main` / `.auth-card`), proving
  it resolved through our `allauth/layouts/entrance.html` override.
- **Unit / integration:**
  - The resolved `account/login.html` is **our** override (template-name / marker assertion).
  - Footer link logic per `signup_policy` (render under open vs invite).
  - **`redirect_field` survives:** a login GET with `?next=/some/path/` renders a hidden
    `name="next"` input carrying that value (guards the I4 redirect regression).
  - Sibling pages render **200 without `{{ form.as_p }}`** (signup, password_reset family,
    accept_invite, sso_not_provisioned).
  - **`account_inactive` is centered** (Bucket A): it renders `main.auth-main` — proves the
    `entrance.html` (not `base_entrance.html`) override point actually catches the direct-extend page.
  - **`extra_body` bridge:** a template extending the entrance chain that emits a marker into
    `{% block extra_body %}` renders that marker through to the page (guards the C2 silent-drop;
    use a tiny test-only template or a flag-enabled allauth page if reachable).
  - `base.html` refactor: existing full-shell pages still render their header + emit
    `extra_head`/`extra_body` defaults (smoke assertion the new blocks didn't disturb them).
- **i18n:** extend the PL gate (`tests/test_i18n_*`) to cover the new auth msgids; **#9b-i18n**
  unifies the JS-notice msgid (one entry, translated). New strings translated; catalog stays
  `0` untranslated / `0` fuzzy / `0` obsolete.
- **DoD gate:** full suite (`-m 'not e2e'`) + the auth e2e green; `ruff check` + `ruff format
  --check`; `manage.py check`; `makemigrations --check` (**no new migration**); `collectstatic`;
  `compilemessages -l pl`.

---

## 7. Task decomposition (for the plan — indicative)

1. `base.html` refactor: `header`/`body_class`/`main_class` blocks **+ `extra_head`/`extra_body`
   blocks** (the allauth-plumbing bridge) + smoke test (existing pages unchanged).
2. `templates/allauth/layouts/entrance.html` override (the entrance common ancestor) + `auth.css`
   skeleton (layout + centered flex column + card + tokens) + style/centering guard (incl.
   `account_inactive` centered).
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

None blocking. Items to **confirm during implementation** (not design decisions):

1. The exact bound-form field set for `LoginForm` / signup / reset under our allauth 65.18
   config (render the named fields explicitly per §3.2, with the graceful-absence fallback).
2. That `site` / `languages` / theme context processors run on allauth-rendered requests
   (they are global; expected present — verify, don't assume).
3. The exact allauth-65.18 context-variable names for the post-login redirect and signup URL
   (`redirect_field` / `signup_url`) as rendered by `LoginView`, so the bespoke `login.html`
   preserves `?next=` (see §4); fall back to a hand-rolled hidden `next` input if absent.
