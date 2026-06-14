# Phase 0d‑1 — UI Foundation: Design Spec

*Spec date: 2026-06-14. First half of Phase 0d (the second, "surfaces", is Phase 0d‑2).
Refines [Phase 0 foundations](2026-06-13-phase-0-foundations-design.md) §5 (i18n) and §6
(theming & branding) and §7 (views). Visual direction is already decided — see
[design-language.md](../../design-language.md) and the accepted mockups in
[docs/mockups](../../mockups/README.md) (`app-shell-light-dark`, `identity-directions_V2`).*

## Goal

Stand up the libli **UI foundation**: a bespoke token-driven CSS system, the reusable
app shell (nav/brand/theme-toggle/language-switch/account-menu), the per-institution
theming-injection mechanism, and the EN/PL i18n infrastructure — then **restyle the
existing auth + home pages** into the real warm-teal identity as the end-to-end proof.
No new product surfaces are built here; the landing page, adaptive dashboard, settings
pages, and error pages are **Phase 0d‑2**, all building on this foundation.

This is the foundation layer: it is depended on by every later view, so it lands first.

## Scope split (why 0d‑1 / 0d‑2)

Phase 0d (i18n + bespoke CSS + UI shell + theming + landing/dashboard/settings + error
pages) is too large for one cycle. It is split:

- **0d‑1 (this spec) — Foundation.** CSS system, app shell, theming injection, i18n
  infrastructure; existing auth + home pages restyled. Demonstrable end-to-end (a real
  branded, themed, EN/PL login/home).
- **0d‑2 — Surfaces.** Public landing page, adaptive dashboard shell, user settings page,
  minimal institution settings page, branded 403/404/500. Each consumes 0d‑1's shell and
  components.

## Success criteria (Definition of Done)

1. The existing auth pages (login, signup, password reset request/confirm, email
   verification, logout, password change) and the home placeholder render inside the new
   **warm-teal app shell** with the bespoke component CSS.
2. A per-user **light/dark/auto** theme toggle works and persists (`User.theme` when
   authenticated, `libli_theme` cookie otherwise). No-flash is guaranteed structurally by a
   pre-paint script ordered before stylesheets (verified by a position+content test, not a
   visual-flash assertion).
3. An **EN↔PL** language switch works, persists (`User.language` when authenticated,
   session otherwise), and shows **real Polish** for the current UI strings; the active
   language set is constrained to `Institution.enabled_languages`.
4. The **institution palette** (`BrandColor` primary/accent) overrides the default warm-teal
   identity by injecting only **two raw CSS variables**; all derived shades and the dark-mode
   lift cascade from them.
5. `collectstatic` succeeds; self-hosted **Inter** and `tokens.css` are served.
6. `pytest` suite green; `ruff` check + format clean; `manage.py check` clean.

---

## Architecture

### New `core` app

A new `core` app owns the cross-cutting UI layer (the Phase 0 spec's "core/web"
component): base templates, the app shell, context processors, the CSS/JS/font static
assets, and the i18n/theme plumbing views. The placeholder `home` view relocates here
from `config/views.py` (it lived in `config/` only because 0b had no UI app yet); its
content stays a placeholder — the real adaptive dashboard is 0d‑2.

**Concrete relocation moves (so `name="home"` stays stable):**
- `config/views.py:home` → `core/views.py:home`.
- `templates/home.html` → `templates/core/home.html`; update the view's
  `render(request, "home.html")` call to `"core/home.html"`.
- Move the `path("home/", home, name="home")` route from `config/urls.py` into
  `core/urls.py` (included from `config/urls.py`), preserving `name="home"` so
  `LOGIN_REDIRECT_URL = "home"` and any `{% url 'home' %}` keep resolving.
- Update `config/urls.py` to `include("core.urls")` and drop its direct `home` import.
  `config/views.py` may then only hold `healthz`. No redirect shim is needed — the `/home/`
  path and `name="home"` both relocate intact via the included `core.urls`.
- **`@login_required` is preserved** on the relocated `home` view: it stays
  authenticated-only and always renders the **authenticated** shell variant (it never
  exercises the anonymous shell). Consequently an unauthenticated request to `/home/`
  redirects (302) to login — the tests fetch `home` as an authenticated client.

```
core/
├── apps.py
├── context_processors.py   # institution_branding (palette/logo/name) + ui_prefs (theme/lang/langs)
├── views.py                # home (relocated); set_ui_language; set_theme
├── urls.py                 # /home/ (moved), /ui/set-language/, /ui/set-theme/
├── templatetags/
│   └── branding.py         # inline brand-vars <style> from the cached Institution palette
└── static/core/
    ├── css/
    │   ├── tokens.css      # raw --brand-* inputs + color-mix-derived palette (light + dark)
    │   ├── reset.css       # base reset, focus rings, prefers-reduced-motion, sr-only
    │   └── app.css         # shell layout + primitive components (nav, buttons, inputs,
    │                       #   form fields, card, alerts, account menu, avatar)
    ├── js/
    │   └── ui.js           # IIFE "use strict": theme toggle, account menu, lang-switch submit
    └── fonts/inter/        # self-hosted Inter woff2; @font-face declared at the top of tokens.css
templates/
├── base.html               # rewritten: full shell, pre-paint script, asset includes, messages
├── core/home.html          # relocated placeholder, now inside the shell
└── allauth/layouts/base.html  # now extends the shell (currently a bare passthrough)
config/
├── settings/base.py        # + "core" in INSTALLED_APPS; LocaleMiddleware; LANGUAGES;
│                           #   LOCALE_PATHS; 2 context processors (no STATICFILES_DIRS)
└── urls.py                 # include("core.urls"); /home/ + name="home" relocate intact
locale/
├── en/LC_MESSAGES/django.po (+ .mo)
└── pl/LC_MESSAGES/django.po (+ .mo)
```

The CSS seed source is the sibling **bonnot** app (on disk at `../bonnot/`): its base
reset, focus-ring, `prefers-reduced-motion`/`sr-only` utilities, spacing (4px grid) and
motion scales, and primitive component CSS are adapted to libli's tokens. We do **not**
adopt React/Vite — CSS only.

### Settings & app registration (load-bearing edits)

- Add `"core"` to `INSTALLED_APPS` (required for `AppDirectoriesFinder` to collect
  `core/static`, for the `branding` template tag to load, and for app templates).
- `core/urls.py` declares `app_name = "core"` so the spec's `core:set_ui_language` /
  `core:set_theme` reverse names resolve; `name="home"` is kept un-namespaced-compatible by
  preserving the existing `name="home"` (so `LOGIN_REDIRECT_URL = "home"` and
  `{% url 'home' %}` are unaffected).
- **Context processors:** append the two `core` processors —
  `core.context_processors.institution_branding` and `core.context_processors.ui_prefs` — to
  the **existing** `TEMPLATES["OPTIONS"]["context_processors"]` list (preserving the current
  `request`, `auth`, `messages` entries). `institution_branding` exposes name/logo/palette;
  `ui_prefs` exposes the resolved theme preference + active/enabled languages for the shell.

### Cached institution accessor

Theming and branding read the singleton `Institution` (+ its `BrandColor` set) on **every**
render. To avoid a per-request DB hit, reads go through a **cached accessor** that resolves
the branding bundle (name, logo URL, the `{primary, accent}` colors map) and stores it in
**Django's cache framework** under a fixed key (e.g. `"core:institution_branding"`) with a
**short TTL** (e.g. 5 minutes). The key is **invalidated on `Institution`/`BrandColor`
`save`/`delete`** via `post_save`/`post_delete` signals.
- **Cache backend reality.** No `CACHES` is defined in `config/settings/*` today, so Django's
  implicit default is `LocMemCache` (per-process). Correctness must therefore **not** depend
  on signal invalidation reaching other workers: the signal clears the *local* worker
  immediately, and the **TTL bounds cross-worker staleness** (a sibling worker serves the old
  palette for at most the TTL after an edit). This is acceptable for branding, which changes
  rarely and only by a PA. Production *may* point `CACHES` at a shared backend to make
  invalidation global — a deployment option, not a 0d‑1 requirement; 0d‑1 is correct under
  the default LocMem because of the TTL.
- Templates degrade gracefully when logo/colors are unset (fall back to defaults).

---

## CSS system & theming (approach A: `color-mix()` from raw brand vars)

### Token derivation

`tokens.css` defines **two raw inputs** and derives everything from them:

```css
:root {
  /* raw institution-overridable inputs (defaults = libli warm teal / amber) */
  --brand-primary: #147E78;
  --brand-accent:  #C77B2A;

  /* derived — light mode */
  --primary:        var(--brand-primary);
  --primary-hover:  color-mix(in srgb, var(--brand-primary) 88%, black);
  --primary-active: color-mix(in srgb, var(--brand-primary) 78%, black);
  --primary-subtle: color-mix(in srgb, var(--brand-primary) 16%, var(--surface-raised));
  --accent:         var(--brand-accent);
  --accent-hover:   color-mix(in srgb, var(--brand-accent) 88%, black);
  --accent-subtle:  color-mix(in srgb, var(--brand-accent) 18%, var(--surface-raised));

  /* surfaces, text, borders, semantic, radii, shadow, spacing, typography:
     literal values straight from design-language.md (+ bonnot scales) */
}

[data-theme="dark"] {
  /* dark surfaces/text/borders/semantic per design-language.md, plus the brand lift */
  --primary:        color-mix(in srgb, var(--brand-primary) 68%, white);
  --primary-hover:  color-mix(in srgb, var(--brand-primary) 78%, white);
  --primary-active: color-mix(in srgb, var(--brand-primary) 88%, white);
  --primary-subtle: color-mix(in srgb, var(--brand-primary) 24%, var(--surface-raised));
  --accent:         color-mix(in srgb, var(--brand-accent) 70%, white);
  /* ... */
}
```

**Which tokens are derived vs literal.** Only the brand families are `color-mix()`-derived:
`--primary`/`--primary-hover`/`--primary-active`/`--primary-subtle` and the `--accent`
pair. Everything else — surfaces, text, borders, semantic colors, radii, shadows, spacing,
typography — is a **flat literal** copied straight from `design-language.md` for each theme
(no derivation). Because CSS custom properties resolve lazily at use-time (not in source
order), the `*-subtle` mixes that reference `var(--surface-raised)` correctly pick up the
**theme-resolved** `--surface-raised` literal (the light value under `:root`, the dark value
under `[data-theme="dark"]`), regardless of declaration order within the rule.

The exact mix percentages are **tuned so the default brand reproduces the hand-picked
values in `design-language.md` closely** — `--primary-hover` ≈ `#0F6A65`, `--primary-active`
≈ `#0B5651`, `--primary-subtle` ≈ `#DCEDEB` (light) / `#1B3A38` (dark), dark `--primary` ≈
`#4FB3AC`, dark `--accent` ≈ `#E5A159`. Implementation must **verify the default brand's
derived values land within a small tolerance of these literals** (eyeball + a hex-diff
check); where a subtle token can't be matched by a single mix, it is acceptable to keep that
specific token as a literal and document the exception. For an arbitrary institution color
the same mixes produce a sensible (approximate) family — the Phase 0 spec already accepts
manual tuning of dark derivation later; this is the documented, tolerated approximation.

`color-mix()` is supported in all current evergreen browsers (Chrome/Edge/Firefox/Safari,
2023+), which is acceptable for this audience.

### Per-institution injection

- A `core` context processor (`institution_branding`) exposes the cached institution
  name/logo (for the nav) and palette.
- `base.html` calls a `core` **`branding` template tag** that renders a **minimal inline
  `<style>`** in `<head>` setting only `--brand-primary`/`--brand-accent`. All shades
  cascade via the `color-mix()` rules above. (The conditional-emit logic lives in the tag
  rather than template `{% if %}` soup.) This keeps the "a school re-themes by editing two
  colors" contract literally true and the per-request inline CSS to ~2 lines.
- **Keys consumed:** exactly the `BrandColor` rows with `key="primary"` and `key="accent"`
  map to `--brand-primary`/`--brand-accent`. Any other `BrandColor` keys are ignored by
  0d‑1 (the model stays open for future named colors, per Phase 0 spec). If `primary` or
  `accent` is **absent**, that variable is simply not emitted and the stylesheet default
  applies. If a present value **equals the default** (`#147E78` / `#C77B2A`), it is likewise
  not emitted (no-op override).
- **Value validation (security invariant).** `BrandColor.value` is admin-editable free text
  and is interpolated into an inline `<style>`, so it MUST be validated against a strict
  CSS-color pattern (hex `#rgb`/`#rrggbb`, or `rgb()/rgba()/hsl()/hsla()` with numeric args)
  **before emission**. Enforce it in **two places**: a model-level `validator` on
  `BrandColor.value` (so the admin form rejects bad input at save time) **and** a final
  guard in the `branding` tag that skips emitting any value failing the pattern (falling
  back to the stylesheet default). A value containing `}`, `<`, `;`, or `</style>` never
  reaches the rendered `<style>`. This closes the CSS/markup-injection vector.
  - The regex is **fully anchored** (`^…$`); surrounding whitespace is **stripped, then
    validated** identically in both the model validator and the tag guard (so `" #147E78 "`
    normalizes to `#147E78`, and an embedded `;`/`}` still fails because the anchored pattern
    permits only color syntax). The existing `max_length=64` comfortably fits every accepted
    form (longest realistic case `hsla(360, 100%, 100%, 0.999)` ≈ 30 chars), so the column
    length and the validator agree.

### Theme attribute & no-flash

- **Two attributes, one resolution rule.** The server renders the **winning-precedence
  preference value verbatim** (one of `light`/`dark`/`auto`) into `<html data-theme-pref="...">`,
  and also renders a best-effort `data-theme="light|dark"` (the `auto`→`light` server
  projection, since the server can't know the OS setting). CSS keys off `data-theme`;
  `data-theme-pref` is what the toggle cycles and what the script reads. Because
  `data-theme-pref` is the resolved-precedence value, the script's `auto` branch fires
  exactly when the resolved preference is `auto` (and never for a concrete `light`/`dark`).
- **Preference source-of-truth precedence:** `User.theme` when authenticated, else the
  `libli_theme` cookie, else `Institution.default_theme` (which itself defaults to `auto`).
  Whichever wins is what lands in `data-theme-pref` verbatim — including `auto`.
- **Pre-paint inline script** (first thing in `<head>`, before any stylesheet `<link>`):
  reads `data-theme-pref` (falling back to the `libli_theme` cookie); **if it is `auto`**,
  it sets `data-theme` to the `prefers-color-scheme` result; **if it is `light` or `dark`**,
  it sets `data-theme` to exactly that and never consults `prefers-color-scheme`. This
  guarantees the script never fights a concrete server-chosen theme and eliminates FOUC
  (including correcting the server's `auto`→`light` placeholder before paint).
- **`libli_theme` cookie:** stores the raw preference (`light`/`dark`/`auto`); attributes
  `Path=/`, `SameSite=Lax`, `Max-Age` ≈ 1 year, `Secure` in production; **not** HttpOnly
  (it is written by `ui.js` client-side).
- **Inter** is self-hosted (`@font-face`, woff2) — no Google Fonts dependency in production.
- whitenoise is already configured. Assets live in **app static** (`core/static/core/...`)
  and are collected automatically by Django's `AppDirectoriesFinder` because `core` is an
  installed app — so **no `STATICFILES_DIRS`** entry is added (adding one for the same files
  would cause a duplicate-path `collectstatic` conflict). `STATIC_ROOT` /
  `CompressedManifestStaticFilesStorage` are already set; the `static/core/` namespacing
  avoids cross-app filename collisions.

---

## UI shell (`base.html`)

Rewritten from the current barebones stub into the reusable chrome from the accepted
`app-shell-light-dark` mockup:

- **Top bar:** the `libli` wordmark + bold **amber dot** (`libli.`, links to home);
  institution **logo** when set (graceful fallback when unset); a right cluster with the
  **language switch** (EN/PL), **theme toggle** (cycles light → dark → auto), and an
  **account menu** (avatar/initials → settings [0d‑2], logout). The avatar is **initials
  only** in 0d‑1 — derived from `User.display_name or User.username` (first letter(s)); there
  is **no uploaded-avatar image field** in this phase. Authenticated vs anonymous variants:
  anonymous shows log-in / sign-up CTAs instead of the account menu.
- **Layout:** responsive single-column shell with a max-width content container; the nav
  collapses to a compact menu on narrow viewports. Template blocks: `head_title`,
  `content`, and `extra_css` / `extra_js` hooks for later pages.
- **Django messages** rendered as styled alerts (success / warning / danger / info) using
  the semantic tokens.
- **JS** — one vanilla IIFE (`ui.js`, `"use strict"`): theme toggle (updates
  `data-theme` + `data-theme-pref` + the `libli_theme` cookie immediately; **then, only
  when the user is authenticated**, a fire-and-forget POST to `set_theme` persists
  `User.theme`), account-menu open/close (with outside-click + Escape), and language-switch
  form submit. Anonymous theme changes are **cookie-only client-side — no POST** (there is
  no server-side state to persist). The `set_theme` POST sends the CSRF token from the
  `csrftoken` cookie via the `X-CSRFToken` header. **Progressive enhancement:** the language
  switch is a real POST `<form>` that works without JS; the theme toggle degrades to its
  server-rendered state.

---

## i18n infrastructure (EN/PL)

- **Settings:** `USE_I18N` is already `True`. Add `django.middleware.locale.LocaleMiddleware`,
  `LOCALE_PATHS = [BASE_DIR / "locale"]`, and a supported set
  `LANGUAGES = [("en", _("English")), ("pl", _("Polski"))]`. **`_` here MUST be
  `gettext_lazy`** (`from django.utils.translation import gettext_lazy as _`) — eager
  `gettext` at settings-import time is a known crash/ordering bug.
- **Exact middleware order.** The current `config/settings/base.py` list is
  `SecurityMiddleware`, `WhiteNoiseMiddleware`, `SessionMiddleware`, `CommonMiddleware`,
  `CsrfViewMiddleware`, `AuthenticationMiddleware`, `MessageMiddleware`,
  `XFrameOptionsMiddleware`, `allauth.account.middleware.AccountMiddleware`. The **only**
  change is inserting `LocaleMiddleware` immediately **after** `SessionMiddleware` and
  **before** `CommonMiddleware` — every other entry, including
  `django.middleware.clickjacking.XFrameOptionsMiddleware`, stays exactly where it is. The
  resulting list: `SecurityMiddleware`, `WhiteNoiseMiddleware`, `SessionMiddleware`,
  **`LocaleMiddleware`**, `CommonMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware`,
  `MessageMiddleware`, `XFrameOptionsMiddleware`, `AccountMiddleware`.
- **Single language-activation mechanism.** `LocaleMiddleware` is the *only* activator: it
  reads the language from the **session** (Django's `_language` session key) / cookie /
  `Accept-Language`, in that order. No middleware reads `request.user` directly. The switch
  view (below) writes the session key; a `user_logged_in` receiver **seeds the session key
  from `User.language`** at login so the middleware then activates it. This avoids the
  "middleware vs receiver" ambiguity — the receiver only seeds the session, the middleware
  always activates.
- **Anonymous / no-session-language seeding.** Django's `LocaleMiddleware` knows nothing
  about `Institution.enabled_languages`; left alone it would honour an `Accept-Language` of
  e.g. `pl` even when the institution has disabled `pl`, falling back only to
  `LANGUAGE_CODE`. To make `Institution.default_language` the real default, a thin custom
  middleware (or the `set_ui_language` path on first contact) **seeds the session language
  key to `Institution.default_language` when the request has no session language and the
  `Accept-Language`-implied language is not in `enabled_languages`.** Net: the active
  language is always within `enabled_languages`, defaulting to `default_language`. This
  custom seeder runs **before** `LocaleMiddleware`.
- **Active-language constraint + stale-preference fallback:** the language switch only
  offers languages in `Institution.enabled_languages`; the effective default falls back to
  `Institution.default_language`. (`LANGUAGES` is the superset libli supports; the
  institution narrows it at runtime.) If a **stored `User.language` is no longer in
  `enabled_languages`** (admin disabled it after the user chose it), the login receiver
  seeds the session with `Institution.default_language` instead — **without mutating the
  stored `User.language`** (so re-enabling the language restores the user's choice).
- **Strings:** mark all current UI strings (shell nav, auth pages, account/settings labels,
  flash messages) with `{% trans %}` / `{% blocktrans %}` in templates and `gettext` in
  Python. Generate `locale/en` + `locale/pl`, write **real Polish** translations, and
  compile `.mo`.
- **Switch view:** a small `core` **`set_ui_language`** POST view (named distinctly to avoid
  colliding with Django's built-in `set_language` view/URL-name — Django's
  `django.conf.urls.i18n` is **not** wired; this custom view fully replaces it because we
  need the `enabled_languages` constraint and `User.language` persistence). It validates the
  requested code is in `Institution.enabled_languages`, writes the session language key, and
  — when authenticated — saves `User.language`; then redirects back. The URL name is pinned
  (e.g. `core:set_ui_language`) so reverse() is unambiguous. Anonymous selection persists in
  the session only.
- **`lang` attribute** on `<html>` reflects the **active** language (not the current
  hardcoded `lang="en"`): derive it via `{% get_current_language as LANGUAGE_CODE %}` and set
  `lang="{{ LANGUAGE_CODE }}"` on the same `<html>` element that carries
  `data-theme`/`data-theme-pref`.

### Theme/language write endpoints vs the settings page

`set_theme` and `set_ui_language` are tiny POST views in `core` — the **inline write path**
for the shell's toggle/switch. The full **user settings page** (explicit theme/language radios,
password change, display name) is **0d‑2**. 0d‑1 ships the inline toggles + endpoints, not a
settings page.

---

## Restyling the existing pages (the proof)

- **allauth pages** (login, signup, password reset request/confirm, email verification,
  logout, password change): styled by making `templates/allauth/layouts/base.html` extend
  the new shell and letting `app.css` style allauth's rendered form fields/buttons globally.
  Thin overrides of individual allauth element templates only where a class hook is genuinely
  needed — kept minimal to avoid drift against allauth's bundled templates.
- **accounts pages** (`accept_invite`, `invite_invalid`, `sso_not_provisioned`): already
  extend `base.html`, so they inherit the shell + styling automatically; light markup tweaks
  (card wrapper) to match the accepted mockup.
- **Shell variant for unauthenticated pages.** The shell renders its **anonymous variant**
  (brand, language switch, theme toggle; **no account menu**) for any request without an
  authenticated user — which covers login/signup/reset and `accept_invite`/`invite_invalid`/
  `sso_not_provisioned`. The anonymous variant's log-in / sign-up CTAs are suppressed on the
  auth pages themselves (login/signup) and on these invite/SSO error pages, since offering
  "log in" there is redundant or wrong; the brand + theme/language controls remain. This is
  driven off `request.user.is_authenticated` plus a `hide_auth_cta` block/flag the auth and
  error templates set.
- **home** (`core/home.html`): relocated into the shell, still placeholder content.

The public **landing page** (site root) is **not** in 0d‑1 — it is a 0d‑2 surface; 0d‑1
leaves the root route as-is.

---

## Data flow (representative)

- **Theme/branding render:** every page → context processors read the cached `Institution`
  (palette/logo/name) and the user's `theme`/`language` → `base.html` sets `lang` and the
  stored `data-theme`, emits the (conditional) inline brand-vars `<style>`, and the pre-paint
  script resolves `auto` before first paint → `tokens.css` derives the full palette via
  `color-mix()`.
- **Theme toggle:** click → `ui.js` flips `data-theme` + `data-theme-pref` + the
  `libli_theme` cookie instantly → **only if authenticated**, a fire-and-forget `set_theme`
  POST persists `User.theme`. Anonymous: cookie-only, no POST.
- **Language switch:** POST `set_ui_language` → validate against `enabled_languages` → write
  session language key + (`User.language` if authed) → redirect back; `LocaleMiddleware`
  activates it on the next request.

## Error handling

- Missing institution logo/colors → graceful fallback to the default identity (no inline
  override emitted when colors equal defaults, absent, or failing color validation).
- `set_theme`/`set_ui_language` with an invalid/disabled value → ignored (no-op), current
  preference preserved. `set_theme` is authed-only; anonymous theme changes are cookie-only
  client-side (no POST). `set_ui_language` for an anonymous user writes the session only.
- `LANGUAGES` superset always present; a value outside `Institution.enabled_languages` is not
  offered and is rejected by the switch view. A stored `User.language` that is later disabled
  falls back to `Institution.default_language` at activation **without** being overwritten.

## Testing

pytest + pytest-django against **real PostgreSQL**; Django test client renders pages. We
test the **wiring**, not pixels:

- Context processors inject institution palette/logo/name + UI theme/lang; the cached
  accessor invalidates on `Institution`/`BrandColor` save.
- Brand override: a non-default `BrandColor` causes the inline `--brand-primary`/
  `--brand-accent` to be emitted; defaults emit none.
- `LocaleMiddleware` active; the switch only offers `Institution.enabled_languages`;
  `set_ui_language` persists to `User.language` (authed) + session (anon); login activates the
  stored language; a known UI string renders in **Polish** when `pl` is active. An anonymous
  request whose `Accept-Language` is a language **not** in `enabled_languages` activates
  `Institution.default_language` (the seeder), not the un-enabled language; a stored
  `User.language` later removed from `enabled_languages` falls back to default at activation
  without being overwritten.
- `BrandColor.value` validation: an invalid/unsafe value (e.g. `red; } body{...`) is rejected
  by the model validator at save, and the `branding` tag emits nothing for a value that fails
  the anchored color pattern (defense-in-depth).
- `set_theme` persists `User.theme` (authed); an anonymous theme change makes **no** server
  POST (cookie-only client-side) — assert the view path is authed-only.
- **No-flash (testable proxy):** assert the pre-paint inline `<script>` is present in `<head>`
  **and appears before any `<link rel="stylesheet">`**, and that it references `data-theme-pref`
  / the `libli_theme` cookie and assigns `data-theme`. (We test *position + content* of the
  script, not the absence of a visual flash, which the test client can't observe.)
- Existing pages extend the shell (brand/nav markers present) with `data-theme`/
  `data-theme-pref` on `<html>`. Fetch state is explicit per page: **anonymous client** for
  `login`, `accept-invite`, `sso-not-provisioned` (assert 200 + the **no-account-menu**
  variant); **authenticated client** for `home` (assert 200 + the authenticated variant, and
  separately that an anonymous `/home/` request 302-redirects to login).
- `collectstatic` succeeds; Inter + `tokens.css` are collected/served.

No DB mocking; no assertions on visual CSS values (only on the presence/contract of injected
vars and attributes).

## Out of scope (→ 0d‑2 and later)

- Public **landing page**, adaptive **dashboard shell**, **user settings page**, minimal
  **institution settings page**, branded **403/404/500** error pages — all 0d‑2.
- Rich branding/SSO/settings admin UIs and the first-run wizard — Phase 5.
- Any course/learning content, DRF endpoints, notifications/exports.
- Content translation (course content) — Phase 1 question; only **UI** strings are i18n'd here.

## Risks

- **Dark-mode brand derivation** from an arbitrary institution color is approximate; mitigated
  by tuning `color-mix()` percentages against the documented default and accepting manual
  tuning later (per the Phase 0 spec's stated tolerance).
- **allauth template restyling** can drift against allauth 65.18's bundled templates; mitigated
  by styling globally via `app.css` + the shared `layouts/base.html` and overriding individual
  allauth templates only when unavoidable.
- **FOUC** if the pre-paint script regresses; covered by a test asserting the script is present
  **and ordered before any stylesheet `<link>`** (position, not just presence) and by keeping
  it inline and first in `<head>`.

---

## Self-review

- **Spec coverage:** new `core` app + file structure ✓; cached institution accessor +
  invalidation ✓; `color-mix()` token derivation from two raw vars + conditional inline
  injection ✓; `data-theme` + pre-paint no-flash + self-hosted Inter ✓; app shell
  (brand/logo/lang-switch/theme-toggle/account-menu, responsive, messages, progressive-
  enhancement JS) ✓; i18n (LocaleMiddleware/LANGUAGES/LOCALE_PATHS, enabled-languages
  constraint, real EN/PL, switch persistence) ✓; theme/lang write endpoints with the settings
  page deferred to 0d‑2 ✓; restyle of existing allauth/accounts/home pages ✓; testing of the
  wiring ✓.
- **Decisions locked:** split 0d‑1/0d‑2; `core` app; approach **A** (`color-mix()` from raw
  `--brand-primary`/`--brand-accent`); full i18n infra with **real EN/PL**; restyle existing
  auth + home pages as the proof.
- **Scope check:** focused on the foundation; every product surface (landing/dashboard/
  settings/errors) is explicitly deferred to 0d‑2, so this is a single coherent plan.
- **Ambiguity check:** theme source-of-truth precedence (User → cookie → institution default)
  and language precedence (User → session, constrained by enabled_languages) are made explicit;
  the inline override is emitted only when colors differ from defaults.
